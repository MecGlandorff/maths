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
#include <utility>
#include <vector>

namespace {
using Vector = std::vector<double>;
using Matrix = std::vector<Vector>;

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
    std::string input, example = "web";
    Vector personalization, start;
    double damping = 0.85, tolerance = 1e-10;
    int maxIterations = 1000;
    bool json = false, trace = false;
};

struct Model {
    Matrix transition, google;
    Vector personalization, initial;
    std::vector<int> dangling;
};

struct State {
    int iteration = 0;
    Vector scores;
    double residual = 0, bound = 0;
};

struct Result {
    State final;
    bool converged = false;
    std::vector<State> history;
};

void usage(std::ostream& out) {
    out << "Usage: pagerank [--example web|cycle|sinks | --input FILE|-]\n"
           "                [--damping D] [--personalization W1,...,Wn] [--start W1,...,Wn]\n"
           "                [--tolerance E] [--max-iterations N] [--trace] [--json]\n"
           "       pagerank --help\n"
           "Input: node count (1..16), then a row-major n*n weight matrix.\n"
           "Rows are source nodes; columns are destinations. Self-loops are allowed.\n"
           "Weights: zero or 1e-12..1e6. Vectors need n entries and a positive sum.\n"
           "Defaults: web example, damping 0.85, uniform personalization and start.\n"
           "Damping: 0..0.99. Tolerance: 1e-12..1e-3 (default 1e-10).\n"
           "Maximum updates: 0..10000 (default 1000). Each option may appear once.\n"
           "--trace includes the initial distribution and every completed update.\n"
           "Exit 0: tolerance met; 2: update limit reached; 1: invalid input.\n";
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
    // Finite nonzero subnormals are valid damping values. Reject overflow and
    // underflow to zero, so an unrepresentable nonzero value is not silently zero.
    if ((errno == ERANGE && value == 0) || end != token.c_str() + token.size() || !std::isfinite(value))
        throw std::invalid_argument("Expected a finite, representable number.");
    return value;
}

double weight(const std::string& token) {
    const double value = decimal(token);
    if (value < 0 || value > 1e6 || (value != 0 && value < 1e-12))
        throw std::invalid_argument("Weights must be zero or between 1e-12 and 1e6.");
    return value;
}

Vector weights(const std::string& text) {
    Vector result;
    std::size_t begin = 0;
    while (true) {
        const auto end = text.find(',', begin);
        if (result.size() == 16) throw std::invalid_argument("Too many vector entries.");
        result.push_back(weight(text.substr(begin, end == std::string::npos ? end : end - begin)));
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    return result;
}

Options options(int argc, char** argv) {
    Options o;
    bool inputSeen = false, exampleSeen = false, dampingSeen = false;
    bool toleranceSeen = false, iterationsSeen = false, personalizationSeen = false, startSeen = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--json" && !o.json) o.json = true;
        else if (arg == "--trace" && !o.trace) o.trace = true;
        else if (arg == "--input" && !inputSeen && i + 1 < argc) {
            inputSeen = true;
            o.input = argv[++i];
            if (o.input.empty()) throw std::invalid_argument("Empty input filename.");
        } else if (arg == "--example" && !exampleSeen && i + 1 < argc) {
            exampleSeen = true;
            o.example = argv[++i];
            if (o.example != "web" && o.example != "cycle" && o.example != "sinks")
                throw std::invalid_argument("Unknown example.");
        } else if (arg == "--damping" && !dampingSeen && i + 1 < argc) {
            dampingSeen = true;
            o.damping = decimal(argv[++i]);
            if (o.damping < 0 || o.damping > 0.99) throw std::invalid_argument("Damping must be 0..0.99.");
        } else if (arg == "--tolerance" && !toleranceSeen && i + 1 < argc) {
            toleranceSeen = true;
            o.tolerance = decimal(argv[++i]);
            if (o.tolerance < 1e-12 || o.tolerance > 1e-3)
                throw std::invalid_argument("Tolerance must be 1e-12..1e-3.");
        } else if (arg == "--max-iterations" && !iterationsSeen && i + 1 < argc) {
            iterationsSeen = true;
            o.maxIterations = integer(argv[++i]);
            if (o.maxIterations > 10000) throw std::invalid_argument("Maximum iterations must be 0..10000.");
        } else if (arg == "--personalization" && !personalizationSeen && i + 1 < argc) {
            personalizationSeen = true;
            o.personalization = weights(argv[++i]);
        } else if (arg == "--start" && !startSeen && i + 1 < argc) {
            startSeen = true;
            o.start = weights(argv[++i]);
        } else throw std::invalid_argument("Unknown, repeated, or incomplete option.");
    }
    if (inputSeen && exampleSeen) throw std::invalid_argument("Choose --input or --example.");
    return o;
}

Matrix readMatrix(std::istream& input) {
    std::string token;
    if (!(input >> token)) throw std::invalid_argument("Missing node count.");
    const int count = integer(token);
    if (count < 1 || count > 16) throw std::invalid_argument("Node count must be 1..16.");
    Matrix matrix(count, Vector(count));
    for (auto& row : matrix)
        for (double& value : row) {
            if (!(input >> token)) throw std::invalid_argument("Missing matrix weight.");
            value = weight(token);
        }
    if (input >> token) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return matrix;
}

Matrix example(const std::string& name) {
    if (name == "web") return {{0, 1, 1, 0}, {0, 0, 1, 0}, {1, 0, 0, 0}, {0, 0, 0, 0}};
    Matrix result(4, Vector(4, 0));
    if (name == "cycle") for (int i = 0; i < 4; ++i) result[i][(i + 1) % 4] = 1;
    return result;
}

Vector distribution(Vector values, std::size_t count) {
    if (values.empty()) return Vector(count, 1 / static_cast<double>(count));
    if (values.size() != count) throw std::invalid_argument("Vector length must match the node count.");
    Sum sum;
    for (double value : values) sum.add(value);
    const double total = sum.value();
    if (total == 0) throw std::invalid_argument("A probability vector needs a positive weight sum.");
    for (double& value : values) value /= total;
    return values;
}

Model model(Matrix matrix, const Options& o) {
    Model m;
    const auto count = matrix.size();
    m.personalization = distribution(o.personalization, count);
    m.initial = distribution(o.start, count);
    for (std::size_t i = 0; i < count; ++i) {
        Sum sum;
        for (double value : matrix[i]) sum.add(value);
        const double total = sum.value();
        if (total == 0) {
            matrix[i] = m.personalization;
            m.dangling.push_back(static_cast<int>(i + 1));
        } else for (double& value : matrix[i]) value /= total;
    }
    m.transition = std::move(matrix);
    m.google = m.transition;
    for (auto& row : m.google)
        for (std::size_t j = 0; j < count; ++j)
            row[j] = std::fma(o.damping, row[j], (1 - o.damping) * m.personalization[j]);
    return m;
}

Vector advance(const Model& m, const Vector& scores, double damping) {
    Vector next(scores.size());
    for (std::size_t j = 0; j < scores.size(); ++j) {
        Sum incoming;
        for (std::size_t i = 0; i < scores.size(); ++i)
            incoming.add(scores[i] * m.transition[i][j]);
        // The affine form contracts even if rounding slightly changes total mass.
        next[j] = std::fma(damping, incoming.value(), (1 - damping) * m.personalization[j]);
    }
    return next;
}

Result solve(const Model& m, const Options& o) {
    Result result;
    result.final.scores = m.initial;
    while (true) {
        Vector next = advance(m, result.final.scores, o.damping);
        Sum residual;
        for (std::size_t j = 0; j < next.size(); ++j)
            residual.add(std::abs(next[j] - result.final.scores[j]));
        result.final.residual = residual.value();
        // In exact arithmetic ||x-x*||_1 <= ||T(x)-x||_1/(1-d), since T is
        // an L1 contraction with factor d. This floating-point value estimates
        // that bound; it does not account for rounding with interval arithmetic.
        result.final.bound = result.final.residual / (1 - o.damping);
        result.converged = result.final.bound <= o.tolerance;
        if (o.trace) result.history.push_back(result.final);
        if (result.converged || result.final.iteration == o.maxIterations) return result;
        result.final.scores = std::move(next);
        ++result.final.iteration;
    }
}

template <typename Values>
void array(const Values& values) {
    std::cout << '[';
    bool first = true;
    for (const auto& value : values) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << value;
    }
    std::cout << ']';
}

std::vector<std::size_t> ranking(const Vector& scores) {
    std::vector<std::size_t> order;
    for (std::size_t i = 0; i < scores.size(); ++i) order.push_back(i);
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return scores[a] == scores[b] ? a < b : scores[a] > scores[b];
    });
    return order;
}

void printJson(const Model& m, const Options& o, const Result& r) {
    std::cout << "{\"nodes\":" << m.initial.size() << ",\"damping\":" << o.damping
              << ",\"tolerance\":" << o.tolerance << ",\"max_iterations\":" << o.maxIterations
              << ",\"personalization\":";
    array(m.personalization);
    std::cout << ",\"initial_scores\":";
    array(m.initial);
    std::cout << ",\"dangling_nodes\":";
    array(m.dangling);
    std::cout << ",\"transition\":[";
    for (std::size_t i = 0; i < m.transition.size(); ++i) {
        if (i != 0) std::cout << ',';
        array(m.transition[i]);
    }
    std::cout << "],\"google_matrix\":[";
    for (std::size_t i = 0; i < m.google.size(); ++i) {
        if (i != 0) std::cout << ',';
        array(m.google[i]);
    }
    std::cout << "],\"scores\":";
    array(r.final.scores);
    std::cout << ",\"ranking\":[";
    bool first = true;
    for (auto node : ranking(r.final.scores)) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "{\"node\":" << node + 1 << ",\"score\":" << r.final.scores[node] << '}';
    }
    std::cout << "],\"iterations\":" << r.final.iteration << ",\"residual_l1\":" << r.final.residual
              << ",\"error_bound\":" << r.final.bound << ",\"converged\":" << (r.converged ? "true" : "false")
              << ",\"stop_reason\":\"" << (r.converged ? "tolerance" : "iteration_limit") << "\",\"history\":[";
    first = true;
    for (const auto& state : r.history) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "{\"iteration\":" << state.iteration << ",\"scores\":";
        array(state.scores);
        std::cout << ",\"residual_l1\":" << state.residual << ",\"error_bound\":" << state.bound << '}';
    }
    std::cout << "]}\n";
}

void printText(const Model& m, const Options& o, const Result& r) {
    std::cout << "PageRank: power iteration for a stationary distribution\nDamping: " << o.damping
              << "\nPersonalization: ";
    array(m.personalization);
    std::cout << "\nInitial scores: ";
    array(m.initial);
    std::cout << "\nDangling nodes (1-based): ";
    array(m.dangling);
    std::cout << "\nTransition matrix (rows: from, columns: to):\n";
    for (const auto& row : m.transition) { array(row); std::cout << '\n'; }
    std::cout << "Google matrix G (rows: from, columns: to):\n";
    for (const auto& row : m.google) { array(row); std::cout << '\n'; }
    std::cout << "node  score\n";
    for (auto node : ranking(r.final.scores)) std::cout << node + 1 << "  " << r.final.scores[node] << '\n';
    std::cout << "Iterations: " << r.final.iteration << "\nResidual L1: " << r.final.residual
              << "\nError bound estimate: " << r.final.bound
              << "\nStop: " << (r.converged ? "tolerance" : "iteration_limit") << '\n';
    if (o.trace) {
        std::cout << "iteration  residual_l1  error_bound  scores\n";
        for (const auto& state : r.history) {
            std::cout << state.iteration << "  " << state.residual << "  " << state.bound << "  ";
            array(state.scores);
            std::cout << '\n';
        }
    }
}
} // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--help") { usage(std::cout); return 0; }
    try {
        const Options o = options(argc, argv);
        Matrix matrix;
        if (o.input.empty()) matrix = example(o.example);
        else if (o.input == "-") matrix = readMatrix(std::cin);
        else {
            std::ifstream input(o.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            matrix = readMatrix(input);
        }
        const Model m = model(std::move(matrix), o);
        const Result r = solve(m, o);
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10);
        if (o.json) printJson(m, o, r);
        else printText(m, o, r);
        return r.converged ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        usage(std::cerr);
        return 1;
    }
}
