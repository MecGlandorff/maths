#include <algorithm>
#include <array>
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
using Pair = std::array<double, 2>;
using Row = std::array<double, 3>;
using Data = std::vector<Row>;

struct Sum {
    double total = 0, correction = 0;
    void add(double value) {
        const double next = total + value;
        correction += std::abs(total) >= std::abs(value)
                    ? (total - next) + value : (value - next) + total;
        total = next;
    }
    double value() const { return total + correction; }
};

struct Options {
    std::string input, example = "near-collinear";
    std::vector<double> lambdas{0, 0.01, 0.1, 1, 10};
    bool json = false;
};

struct Geometry {
    Data centered;
    Row means{};
    double a = 0, cross = 0, b = 0, threshold = 0;
    Pair eigenvalues{};
    std::array<Pair, 2> eigenvectors{{{1, 0}, {0, 1}}};
    int rank = 0;
};

struct Fit {
    double lambda, bias = 0, loss = 0, penalty = 0, norm = 0;
    Pair weights{};
    std::vector<double> predictions, residuals;
    Pair shrinkage{};
    double effectiveDf = 1; // The unpenalized intercept contributes one.
};

void usage(std::ostream& out) {
    out << "Usage: ridge_regression [--example near-collinear|collinear|orthogonal | --input FILE|-]\n"
           "                        [--lambdas L1,L2,...] [--json]\n"
           "       ridge_regression --help\n"
           "Model: y = bias + w1*x1 + w2*x2; the intercept is not penalized.\n"
           "Objective: mean(residual^2)/2 + lambda*(w1^2+w2^2)/2.\n"
           "Defaults: near-collinear example; lambdas 0,0.01,0.1,1,10.\n"
           "Input: sample count (1..256), then that many x1 x2 y triples.\n"
           "Values: zero or magnitudes 1e-6..1e3, in decimal notation.\n"
           "Lambdas: 1..8 unique values, each zero or 1e-6..1e6, in requested order.\n"
           "Inputs are centered, not rescaled. Each option may appear once.\n";
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

std::vector<double> lambdas(const std::string& text) {
    std::vector<double> values;
    std::size_t begin = 0;
    while (true) {
        const std::size_t end = text.find(',', begin);
        const double value = decimal(text.substr(begin, end == std::string::npos ? end : end - begin));
        if (value < 0 || value > 1e6 || (value != 0 && value < 1e-6))
            throw std::invalid_argument("Lambda must be zero or between 1e-6 and 1e6.");
        if (values.size() == 8 || std::find(values.begin(), values.end(), value) != values.end())
            throw std::invalid_argument("Provide 1..8 unique lambda values.");
        values.push_back(value);
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    return values;
}

Options options(int argc, char** argv) {
    Options result;
    bool inputSeen = false, exampleSeen = false, lambdasSeen = false;
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
            if (result.example != "near-collinear" && result.example != "collinear"
                && result.example != "orthogonal")
                throw std::invalid_argument("Unknown example.");
        } else if (arg == "--lambdas" && !lambdasSeen && i + 1 < argc) {
            lambdasSeen = true;
            result.lambdas = lambdas(argv[++i]);
        } else {
            throw std::invalid_argument("Unknown, repeated, or incomplete option.");
        }
    }
    if (inputSeen && exampleSeen) throw std::invalid_argument("Choose --input or --example.");
    return result;
}

Data readData(std::istream& input) {
    std::string token;
    if (!(input >> token)) throw std::invalid_argument("Missing sample count.");
    const int count = integer(token);
    if (count < 1 || count > 256) throw std::invalid_argument("Sample count must be 1..256.");
    Data data(count);
    for (auto& row : data)
        for (double& value : row) {
            if (!(input >> token)) throw std::invalid_argument("Missing x1 x2 y triple.");
            value = decimal(token);
            if (std::abs(value) > 1e3 || (value != 0 && std::abs(value) < 1e-6))
                throw std::invalid_argument("Values must be zero or have magnitude 1e-6..1e3.");
        }
    if (input >> token) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return data;
}

Data example(const std::string& name) {
    Data data;
    const std::array<int, 5> q{1, -2, 2, -2, 1};
    for (int i = 0; i < 5; ++i) {
        const double t = i - 2;
        if (name == "collinear") data.push_back({t, t, 1 + 3 * t});
        else if (name == "orthogonal") data.push_back({t, static_cast<double>(q[i]), 1 + 3 * t - 2 * q[i]});
        else data.push_back({t, t + 0.01 * q[i], 1 + 3 * t + 0.1 * q[i]});
    }
    return data;
}

double differenceOfProducts(double a, double b, double c, double d) {
    const double cd = c * d;
    return std::fma(a, b, -cd) + std::fma(-c, d, cd);
}

Geometry geometry(const Data& data) {
    Geometry g;
    const double count = static_cast<double>(data.size());
    Row offsets{};
    for (int j = 0; j < 3; ++j) {
        Sum raw, shifted;
        for (const auto& row : data) {
            raw.add(row[j]);
            shifted.add(row[j] - data.front()[j]);
        }
        g.means[j] = raw.value() / count;
        offsets[j] = shifted.value() / count;
    }
    for (const auto& row : data) {
        Row centered{};
        for (int j = 0; j < 3; ++j)
            centered[j] = (row[j] - data.front()[j]) - offsets[j];
        g.centered.push_back(centered);
    }
    Sum a, cross, b, minors;
    for (const auto& row : g.centered) {
        a.add(row[0] * row[0]);
        cross.add(row[0] * row[1]);
        b.add(row[1] * row[1]);
    }
    g.a = a.value() / count;
    g.cross = cross.value() / count;
    g.b = b.value() / count;
    g.eigenvalues[0] = (g.a + g.b + std::hypot(g.a - g.b, 2 * g.cross)) / 2;
    // Cauchy-Binet: det(X'X/n) is the sum of squared two-row minors / n^2.
    // This avoids cancellation in a*b - cross*cross for nearly dependent columns.
    for (std::size_t i = 0; i < data.size(); ++i)
        for (std::size_t j = i + 1; j < data.size(); ++j) {
            const auto& u = g.centered[i];
            const auto& v = g.centered[j];
            const double minor = differenceOfProducts(u[0], v[1], u[1], v[0]);
            minors.add(minor * minor);
        }
    if (g.eigenvalues[0] > 0)
        g.eigenvalues[1] = std::min(g.eigenvalues[0], minors.value() / (count * count) / g.eigenvalues[0]);
    if (g.cross == 0) {
        if (g.b > g.a) g.eigenvectors = {{{0, 1}, {1, 0}}};
    } else {
        const double angle = std::atan2(2 * g.cross, g.a - g.b) / 2;
        const double c = std::cos(angle), s = std::sin(angle);
        g.eigenvectors = {{{c, s}, {-s, c}}};
    }
    g.threshold = 64 * std::numeric_limits<double>::epsilon() * g.eigenvalues[0];
    for (double value : g.eigenvalues) if (value > g.threshold) ++g.rank;
    return g;
}

Fit fit(const Data& data, const Geometry& g, double lambda) {
    Fit result{lambda, 0, 0, 0, 0, {}, {}, {}, {}, 1};
    const double count = static_cast<double>(data.size());
    for (int j = 0; j < 2; ++j) {
        const double value = g.eigenvalues[j];
        result.shrinkage[j] = lambda > 0 ? value / (value + lambda)
                                       : (value > g.threshold ? 1 : 0);
        result.effectiveDf += result.shrinkage[j];
    }
    if (lambda == 0 && g.rank == 1) {
        const auto& direction = g.eigenvectors[0];
        Sum projected;
        for (const auto& row : g.centered)
            projected.add(std::fma(direction[0], row[0], direction[1] * row[1]) * row[2]);
        const double coefficient = projected.value() / count / g.eigenvalues[0];
        result.weights = {coefficient * direction[0], coefficient * direction[1]};
    } else if (lambda > 0 || g.rank == 2) {
        const int p = g.a >= g.b ? 0 : 1;
        const int q = 1 - p;
        const double pivot = (p == 0 ? g.a : g.b) + lambda;
        const double rho = g.cross / pivot;
        Sum firstTarget, secondTarget, residualSquares, residualCross;
        for (const auto& row : g.centered) {
            const double residualFeature = std::fma(-rho, row[p], row[q]);
            firstTarget.add(row[p] * row[2]);
            secondTarget.add(residualFeature * row[2]);
            residualSquares.add(residualFeature * residualFeature);
            residualCross.add(row[p] * residualFeature);
        }
        // In the basis (u, v-rho*u), rounded rho leaves a small off-diagonal
        // term delta. Keeping it matters when lambda is tiny next to Var(u).
        const double delta = std::fma(-lambda, rho, residualCross.value() / count);
        const double diagonal = residualSquares.value() / count + lambda * (1 + rho * rho);
        const double denominator = std::fma(-delta / pivot, delta, diagonal);
        const double first = firstTarget.value() / count / pivot;
        result.weights[q] = std::fma(-delta, first, secondTarget.value() / count) / denominator;
        result.weights[p] = std::fma(-rho, result.weights[q],
                                    std::fma(-delta / pivot, result.weights[q], first));
    }
    Sum intercepts, squares;
    for (std::size_t i = 0; i < data.size(); ++i) {
        const auto& row = data[i];
        const auto& centered = g.centered[i];
        intercepts.add(std::fma(-result.weights[0], row[0],
                               std::fma(-result.weights[1], row[1], row[2])));
        const double fitted = std::fma(result.weights[0], centered[0], result.weights[1] * centered[1]);
        const double residual = fitted - centered[2];
        result.predictions.push_back(g.means[2] + fitted);
        result.residuals.push_back(residual);
        squares.add(residual * residual);
    }
    result.bias = intercepts.value() / count;
    result.loss = squares.value() / (2 * count);
    result.norm = std::hypot(result.weights[0], result.weights[1]);
    result.penalty = lambda * result.norm * result.norm / 2;
    return result;
}

template <typename Values>
void array(const Values& values) {
    std::cout << '[';
    bool first = true;
    for (double value : values) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << value;
    }
    std::cout << ']';
}

void condition(const Geometry& g, double lambda, bool json) {
    if (lambda == 0 && g.rank < 2) std::cout << (json ? "null" : "undefined");
    else std::cout << (g.eigenvalues[0] + lambda) / (g.eigenvalues[1] + lambda);
}

void printJson(const Data& data, const Geometry& g, const std::vector<Fit>& fits) {
    std::cout << "{\"samples\":" << data.size() << ",\"feature_means\":";
    array(Pair{g.means[0], g.means[1]});
    std::cout << ",\"target_mean\":" << g.means[2]
              << ",\"covariance\":[[" << g.a << ',' << g.cross << "],[" << g.cross << ',' << g.b << "]]"
              << ",\"eigenvalues\":";
    array(g.eigenvalues);
    std::cout << ",\"eigenvectors\":[";
    array(g.eigenvectors[0]);
    std::cout << ',';
    array(g.eigenvectors[1]);
    std::cout << "],\"rank\":" << g.rank << ",\"rank_threshold\":" << g.threshold
              << ",\"condition_number\":";
    condition(g, 0, true);
    std::cout << ",\"fits\":[";
    bool first = true;
    for (const auto& f : fits) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "{\"lambda\":" << f.lambda << ",\"bias\":" << f.bias << ",\"weights\":";
        array(f.weights);
        std::cout << ",\"data_loss\":" << f.loss << ",\"penalty\":" << f.penalty
                  << ",\"objective\":" << f.loss + f.penalty << ",\"weight_norm\":" << f.norm
                  << ",\"shrinkage\":";
        array(f.shrinkage);
        std::cout << ",\"effective_df\":" << f.effectiveDf << ",\"regularized_condition\":";
        condition(g, f.lambda, true);
        std::cout << ",\"predictions\":";
        array(f.predictions);
        std::cout << ",\"residuals\":";
        array(f.residuals);
        std::cout << '}';
    }
    std::cout << "]}\n";
}

void printText(const Data& data, const Geometry& g, const std::vector<Fit>& fits) {
    std::cout << "Ridge regression: y = bias + w1*x1 + w2*x2\nSamples: " << data.size()
              << "\nThe intercept is unpenalized; features are centered without rescaling.\n"
              << "Feature means: " << g.means[0] << ", " << g.means[1] << "\nTarget mean: " << g.means[2]
              << "\nCovariance: [[" << g.a << ", " << g.cross << "], [" << g.cross << ", " << g.b << "]]"
              << "\nEigenvalues (descending): " << g.eigenvalues[0] << ", " << g.eigenvalues[1]
              << "\nEigenvectors (same order): [" << g.eigenvectors[0][0] << ", " << g.eigenvectors[0][1]
              << "], [" << g.eigenvectors[1][0] << ", " << g.eigenvectors[1][1] << ']'
              << "\nNumerical rank: " << g.rank << "\nRank threshold: " << g.threshold << "\nCondition number: ";
    condition(g, 0, false);
    std::cout << "\nlambda  bias  w1  w2  data_loss  penalty  objective  weight_norm\n";
    for (const auto& f : fits)
        std::cout << f.lambda << "  " << f.bias << "  " << f.weights[0] << "  " << f.weights[1]
                  << "  " << f.loss << "  " << f.penalty << "  " << f.loss + f.penalty << "  " << f.norm << '\n';
    std::cout << "\nSpectral effects\nlambda  shrink_max  shrink_min  effective_df  regularized_condition\n";
    for (const auto& f : fits) {
        std::cout << f.lambda << "  " << f.shrinkage[0] << "  " << f.shrinkage[1] << "  " << f.effectiveDf << "  ";
        condition(g, f.lambda, false);
        std::cout << '\n';
    }
    if (g.rank < 2)
        std::cout << "At lambda=0, directions at or below the rank threshold are discarded.\n";
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
        if (config.input.empty()) data = example(config.example);
        else if (config.input == "-") data = readData(std::cin);
        else {
            std::ifstream input(config.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            data = readData(input);
        }
        const Geometry g = geometry(data);
        std::vector<Fit> fits;
        for (double lambda : config.lambdas) fits.push_back(fit(data, g, lambda));
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10);
        if (config.json) printJson(data, g, fits);
        else printText(data, g, fits);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        usage(std::cerr);
        return 1;
    }
}
