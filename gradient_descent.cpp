#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Sample { double x, y; };
using Data = std::vector<Sample>;

struct Options {
    std::string input;
    std::string example = "centered";
    double rate = 0; // Zero selects 1 / the largest Hessian eigenvalue.
    double bias = 0, weight = 0;
    int steps = 12;
    bool json = false;
};

// Compensated sums also retain small terms when a large term cancels later.
struct Sum {
    double sum = 0, correction = 0;
    void add(double value) {
        const double next = sum + value;
        correction += std::abs(sum) >= std::abs(value)
                    ? (sum - next) + value : (value - next) + sum;
        sum = next;
    }
    double value() const { return sum + correction; }
};

struct Geometry {
    double xAnchor, yAnchor, xOffset, yOffset;
    double meanX, meanY, variance, covariance, meanSquare, largest;
};

struct State {
    int step;
    double bias, weight, loss, biasGradient, weightGradient;
};

struct Run {
    std::vector<State> trajectory;
    bool limited = false;
};

struct Analysis {
    int rank;
    double smallest, condition, upperRate, contraction;
    double referenceBias, referenceWeight, referenceLoss;
    std::string regime;
};

void usage(std::ostream& out) {
    out << "Usage: gradient_descent [--example centered|shifted|constant | --input FILE|-]\n"
           "                        [--rate R] [--steps N] [--start B W] [--json]\n"
           "       gradient_descent --help\n"
           "Fits y = bias + weight*x with mean squared error divided by two.\n"
           "Defaults: centered example, rate 1/lambda_max, 12 steps, start (0,0).\n"
           "Input: sample count (1..256), then that many x y pairs.\n"
           "Values and starts: zero or magnitudes 1e-6..1e6; decimal notation.\n"
           "Rate: 1e-15..1e6. Steps: 0..1000. Each option may appear once.\n"
           "Stops before a coefficient would exceed magnitude 1e100 (exit 2).\n";
}

int integer(const std::string& token) {
    int value = 0;
    if (token.empty() || token.front() < '0' || token.front() > '9')
        throw std::invalid_argument("Expected an unsigned integer.");
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size())
        throw std::invalid_argument("Expected an unsigned integer.");
    return value;
}

double decimal(const std::string& token) {
    // strtod also accepts hexadecimal and NaN; our input format does not.
    std::size_t pos = 0;
    if (pos < token.size() && (token[pos] == '+' || token[pos] == '-')) ++pos;
    bool digits = false;
    const auto consumeDigits = [&]() {
        while (pos < token.size() && token[pos] >= '0' && token[pos] <= '9') {
            digits = true;
            ++pos;
        }
    };
    consumeDigits();
    if (pos < token.size() && token[pos] == '.') {
        ++pos;
        consumeDigits();
    }
    if (!digits) throw std::invalid_argument("Expected a decimal number.");
    if (pos < token.size() && (token[pos] == 'e' || token[pos] == 'E')) {
        ++pos;
        if (pos < token.size() && (token[pos] == '+' || token[pos] == '-')) ++pos;
        digits = false;
        consumeDigits();
        if (!digits) throw std::invalid_argument("Incomplete exponent.");
    }
    if (pos != token.size()) throw std::invalid_argument("Expected a decimal number.");
    errno = 0;
    char* end = nullptr;
    const double value = std::strtod(token.c_str(), &end);
    if (errno == ERANGE || end != token.c_str() + token.size() || !std::isfinite(value))
        throw std::invalid_argument("Expected a finite, representable number.");
    return value;
}

double coordinate(const std::string& token) {
    const double value = decimal(token);
    if (std::abs(value) > 1e6 || (value != 0 && std::abs(value) < 1e-6))
        throw std::invalid_argument("Values must be zero or have magnitude 1e-6..1e6.");
    return value;
}

Options options(int argc, char** argv) {
    Options result;
    bool inputSeen = false, exampleSeen = false, rateSeen = false;
    bool stepsSeen = false, startSeen = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--json" && !result.json) {
            result.json = true;
        } else if (arg == "--input" && !inputSeen && i + 1 < argc) {
            inputSeen = true;
            result.input = argv[++i];
            if (result.input.empty()) throw std::invalid_argument("Empty input filename.");
        } else if (arg == "--example" && !exampleSeen && i + 1 < argc) {
            exampleSeen = true;
            result.example = argv[++i];
            if (result.example != "centered" && result.example != "shifted"
                && result.example != "constant")
                throw std::invalid_argument("Unknown example.");
        } else if (arg == "--rate" && !rateSeen && i + 1 < argc) {
            rateSeen = true;
            result.rate = decimal(argv[++i]);
            if (result.rate < 1e-15 || result.rate > 1e6)
                throw std::invalid_argument("Rate must be between 1e-15 and 1e6.");
        } else if (arg == "--steps" && !stepsSeen && i + 1 < argc) {
            stepsSeen = true;
            result.steps = integer(argv[++i]);
            if (result.steps > 1000) throw std::invalid_argument("Steps must be 0..1000.");
        } else if (arg == "--start" && !startSeen && i + 2 < argc) {
            startSeen = true;
            result.bias = coordinate(argv[++i]);
            result.weight = coordinate(argv[++i]);
        } else {
            throw std::invalid_argument("Unknown, repeated, or incomplete option.");
        }
    }
    if (inputSeen && exampleSeen)
        throw std::invalid_argument("Choose --input or --example.");
    return result;
}

Data readData(std::istream& input) {
    std::string token;
    if (!(input >> token)) throw std::invalid_argument("Missing sample count.");
    const int count = integer(token);
    if (count < 1 || count > 256) throw std::invalid_argument("Sample count must be 1..256.");
    Data data;
    for (int i = 0; i < count; ++i) {
        std::string x, y;
        if (!(input >> x >> y)) throw std::invalid_argument("Missing x y pair.");
        data.push_back({coordinate(x), coordinate(y)});
    }
    if (input >> token) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return data;
}

Data example(const std::string& name) {
    Data data;
    for (int i = -2; i <= 2; ++i) {
        const double x = name == "constant" ? 2 : i + (name == "shifted" ? 100 : 0);
        data.push_back({x, static_cast<double>(1 + 2 * i)});
    }
    return data;
}

Geometry geometry(const Data& data) {
    Geometry g{};
    g.xAnchor = data.front().x;
    g.yAnchor = data.front().y;
    const double count = static_cast<double>(data.size());
    Sum x, y, rawX, rawY;
    for (const auto& row : data) {
        x.add(row.x - g.xAnchor);
        y.add(row.y - g.yAnchor);
        rawX.add(row.x);
        rawY.add(row.y);
    }
    g.xOffset = x.value() / count;
    g.yOffset = y.value() / count;
    g.meanX = rawX.value() / count;
    g.meanY = rawY.value() / count;
    Sum variance, covariance;
    for (const auto& row : data) {
        // Keep the mean as anchor + offset: adjacent doubles can have a mean
        // that is not itself representable, even when their variance is.
        const double dx = (row.x - g.xAnchor) - g.xOffset;
        const double dy = (row.y - g.yAnchor) - g.yOffset;
        variance.add(dx * dx);
        covariance.add(dx * dy);
    }
    g.variance = variance.value() / count;
    g.covariance = covariance.value() / count;
    g.meanSquare = std::fma(g.meanX, g.meanX, g.variance);
    g.largest = (1 + g.meanSquare + std::hypot(1 - g.meanSquare, 2 * g.meanX)) / 2;
    return g;
}

Analysis analyze(const Data& data, const Geometry& g, double rate) {
    Analysis a{};
    a.rank = g.variance == 0 ? 1 : 2;
    // det(H) = Var(x). Subtracting the two roots loses the smaller one
    // when the feature has a large offset or very little variation.
    a.smallest = g.variance / g.largest;
    a.condition = a.rank == 1 ? 0 : g.largest / a.smallest;
    a.upperRate = 2 / g.largest;
    const double scaledRate = rate * g.largest;
    a.regime = scaledRate < 2 ? "contracting" : (scaledRate == 2 ? "boundary" : "unstable");
    a.contraction = std::abs(1 - scaledRate);
    if (a.rank == 2)
        a.contraction = std::max(a.contraction, std::abs(1 - rate * a.smallest));

    if (a.rank == 1) {
        // Among b + c*w = mean(y), this is the minimum Euclidean norm pair.
        a.referenceBias = g.meanY / (1 + g.meanSquare);
        a.referenceWeight = g.meanX * a.referenceBias;
    } else {
        a.referenceWeight = g.covariance / g.variance;
        Sum intercepts;
        for (const auto& row : data)
            intercepts.add(std::fma(-a.referenceWeight, row.x, row.y));
        a.referenceBias = intercepts.value() / static_cast<double>(data.size());
    }
    Sum squares;
    for (const auto& row : data) {
        const double dx = (row.x - g.xAnchor) - g.xOffset;
        const double dy = (row.y - g.yAnchor) - g.yOffset;
        const double residual = std::fma(a.referenceWeight, dx, -dy);
        squares.add(residual * residual);
    }
    a.referenceLoss = squares.value() / (2 * static_cast<double>(data.size()));
    return a;
}

State evaluate(const Data& data, int step, double bias, double weight) {
    Sum squares, biasGradient, weightGradient;
    for (const auto& row : data) {
        const double residual = std::fma(weight, row.x, bias) - row.y;
        squares.add(residual * residual);
        biasGradient.add(residual);
        weightGradient.add(row.x * residual);
    }
    const double count = static_cast<double>(data.size());
    return {step, bias, weight, squares.value() / (2 * count),
            biasGradient.value() / count, weightGradient.value() / count};
}

Run descend(const Data& data, const Options& config, double rate) {
    Run result;
    result.trajectory.push_back(evaluate(data, 0, config.bias, config.weight));
    for (int step = 1; step <= config.steps; ++step) {
        const auto& previous = result.trajectory.back();
        const double bias = std::fma(-rate, previous.biasGradient, previous.bias);
        const double weight = std::fma(-rate, previous.weightGradient, previous.weight);
        if (!std::isfinite(bias) || !std::isfinite(weight)
            || std::abs(bias) > 1e100 || std::abs(weight) > 1e100) {
            result.limited = true;
            break;
        }
        result.trajectory.push_back(evaluate(data, step, bias, weight));
    }
    return result;
}

void printJson(const Data& data, const Options& config, const Geometry& g,
               const Analysis& a, double rate, const Run& run) {
    std::cout << "{\"samples\":" << data.size() << ",\"learning_rate\":" << rate
              << ",\"hessian\":[[1," << g.meanX << "],[" << g.meanX << ',' << g.meanSquare << "]]"
              << ",\"eigenvalues\":[" << a.smallest << ',' << g.largest << ']'
              << ",\"rank\":" << a.rank << ",\"condition_number\":";
    if (a.rank == 1) std::cout << "null";
    else std::cout << a.condition;
    std::cout << ",\"stable_rate_upper_bound\":" << a.upperRate
              << ",\"rate_regime\":\"" << a.regime << "\",\"contraction_factor\":" << a.contraction
              << ",\"reference\":{\"bias\":" << a.referenceBias << ",\"weight\":" << a.referenceWeight
              << ",\"loss\":" << a.referenceLoss << '}'
              << ",\"requested_steps\":" << config.steps
              << ",\"completed_steps\":" << run.trajectory.back().step
              << ",\"stop_reason\":\"" << (run.limited ? "magnitude_limit" : "steps_completed")
              << "\",\"trajectory\":[";
    bool first = true;
    for (const auto& state : run.trajectory) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "{\"step\":" << state.step << ",\"bias\":" << state.bias
                  << ",\"weight\":" << state.weight << ",\"loss\":" << state.loss
                  << ",\"gradient\":[" << state.biasGradient << ',' << state.weightGradient << "]}";
    }
    std::cout << "]}\n";
}

void printText(const Data& data, const Geometry& g, const Analysis& a, double rate, const Run& run) {
    std::cout << "Gradient descent: y = bias + weight*x\n"
              << "Samples: " << data.size() << "\nHessian: [[1, " << g.meanX << "], ["
              << g.meanX << ", " << g.meanSquare << "]]\n"
              << "Eigenvalues (ascending): " << a.smallest << ", " << g.largest
              << "\nRank: " << a.rank << "\nCondition number: ";
    if (a.rank == 1) std::cout << "undefined (singular)";
    else std::cout << a.condition;
    std::cout << "\nLearning rate: " << rate << "\nContracting interval: 0 < rate < " << a.upperRate
              << "\nRate regime: " << a.regime
              << "\nWorst error factor on positive-curvature directions: " << a.contraction
              << "\nReference fit: bias=" << a.referenceBias << ", weight=" << a.referenceWeight
              << ", loss=" << a.referenceLoss << '\n';
    if (a.rank == 1)
        std::cout << "Reference has minimum norm; a nonzero start can retain a nullspace component.\n";
    std::cout << "step  bias  weight  loss  gradient_bias  gradient_weight\n";
    for (const auto& state : run.trajectory)
        std::cout << state.step << "  " << state.bias << "  " << state.weight
                  << "  " << state.loss << "  " << state.biasGradient << "  " << state.weightGradient << '\n';
    std::cout << "Stop: " << (run.limited ? "magnitude_limit" : "steps_completed") << '\n';
}
} // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--help") {
        usage(std::cout);
        return 0;
    }
    try {
        const Options config = options(argc, argv);
        Data data;
        if (config.input.empty()) {
            data = example(config.example);
        } else if (config.input == "-") {
            data = readData(std::cin);
        } else {
            std::ifstream input(config.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            data = readData(input);
        }
        const Geometry g = geometry(data);
        const double rate = config.rate == 0 ? 1 / g.largest : config.rate;
        const Analysis a = analyze(data, g, rate);
        const Run run = descend(data, config, rate);
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10);
        if (config.json) printJson(data, config, g, a, rate, run);
        else printText(data, g, a, rate, run);
        return run.limited ? 2 : 0;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        usage(std::cerr);
        return 1;
    }
}
