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
using Vector = std::vector<double>;
using Matrix = std::vector<Vector>;

struct Options {
    std::string input;
    double temperature = 1;
    bool causal = false;
    bool backward = false;
    bool json = false;
};

struct Data {
    int queries, keys, keyDimensions, valueDimensions;
    Matrix query, key, value, upstream;
};

struct Result {
    Matrix scores, weights, output;
    Vector entropy;
    Matrix queryGradient, keyGradient, valueGradient;
    double objective = 0;
};

void usage(std::ostream& out) {
    out << "Usage: attention [--input FILE|-] [--temperature T] [--causal] [--backward] [--json]\n"
           "       attention --help\n"
           "Default: three queries and keys, with two-dimensional keys and values.\n"
           "Input: m n dk dv, then row-major Q (m*dk), K (n*dk), V (n*dv).\n"
           "With --backward, append G (m*dv), the upstream derivative dL/dO.\n"
           "Limits: m,n=1..16; dk,dv=1..8; nonzero magnitudes 1e-100..1e6.\n"
           "Temperature: 1e-3..1e3 (default 1). Causal mode requires m=n.\n";
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

double number(const std::string& token) {
    // strtod also accepts hex and NaN; restrict the public format to decimal numbers.
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
    if (errno == ERANGE || end != token.c_str() + token.size() || !std::isfinite(value)
        || std::abs(value) > 1e6 || (value != 0 && std::abs(value) < 1e-100))
        throw std::invalid_argument("Value outside the supported numeric range.");
    return value;
}

Options options(int argc, char** argv) {
    Options result;
    bool inputSeen = false, temperatureSeen = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--json" && !result.json) {
            result.json = true;
        } else if (arg == "--causal" && !result.causal) {
            result.causal = true;
        } else if (arg == "--backward" && !result.backward) {
            result.backward = true;
        } else if (arg == "--input" && !inputSeen && i + 1 < argc) {
            inputSeen = true;
            result.input = argv[++i];
            if (result.input.empty()) throw std::invalid_argument("Empty input filename.");
        } else if (arg == "--temperature" && !temperatureSeen && i + 1 < argc) {
            temperatureSeen = true;
            result.temperature = number(argv[++i]);
            if (result.temperature < 1e-3 || result.temperature > 1e3)
                throw std::invalid_argument("Temperature must be between 1e-3 and 1e3.");
        } else {
            throw std::invalid_argument("Unknown, repeated, or incomplete option.");
        }
    }
    return result;
}

Matrix readMatrix(std::istream& input, int rows, int columns) {
    Matrix matrix(rows, Vector(columns));
    std::string token;
    for (auto& row : matrix)
        for (double& value : row) {
            if (!(input >> token)) throw std::invalid_argument("Not enough matrix values.");
            value = number(token);
        }
    return matrix;
}

Data readData(std::istream& input, bool backward) {
    std::string m, n, dk, dv;
    if (!(input >> m >> n >> dk >> dv)) throw std::invalid_argument("Missing input dimensions.");
    Data data{integer(m), integer(n), integer(dk), integer(dv), {}, {}, {}, {}};
    if (data.queries < 1 || data.queries > 16 || data.keys < 1 || data.keys > 16
        || data.keyDimensions < 1 || data.keyDimensions > 8
        || data.valueDimensions < 1 || data.valueDimensions > 8)
        throw std::invalid_argument("Input dimensions outside the supported range.");
    data.query = readMatrix(input, data.queries, data.keyDimensions);
    data.key = readMatrix(input, data.keys, data.keyDimensions);
    data.value = readMatrix(input, data.keys, data.valueDimensions);
    if (backward) data.upstream = readMatrix(input, data.queries, data.valueDimensions);
    std::string extra;
    if (input >> extra) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return data;
}

Data demo() {
    return {3, 3, 2, 2, {{1, 0}, {0, 1}, {1, 1}},
            {{1, 0}, {0, 1}, {-1, 1}}, {{1, 0}, {0, 2}, {-1, -1}},
            {{1, 0.5}, {-0.5, 1}, {0.25, -1}}};
}

Result attention(const Data& data, const Options& config) {
    if (config.causal && data.queries != data.keys)
        throw std::invalid_argument("Causal mode requires equal query and key counts.");
    Result result;
    result.scores.assign(data.queries, Vector(data.keys, 0));
    result.weights.assign(data.queries, Vector(data.keys, 0));
    result.output.assign(data.queries, Vector(data.valueDimensions, 0));
    result.entropy.assign(data.queries, 0);
    const double scale = 1 / (std::sqrt(static_cast<double>(data.keyDimensions)) * config.temperature);
    for (int i = 0; i < data.queries; ++i) {
        for (int j = 0; j < data.keys; ++j) {
            double dot = 0;
            for (int d = 0; d < data.keyDimensions; ++d) dot += data.query[i][d] * data.key[j][d];
            result.scores[i][j] = dot * scale;
        }
        const int visible = config.causal ? i + 1 : data.keys;
        // Exclude masked positions from BOTH the maximum and the denominator.
        const double maximum = *std::max_element(result.scores[i].begin(),
                                                 result.scores[i].begin() + visible);
        double denominator = 0;
        for (int j = 0; j < visible; ++j) {
            result.weights[i][j] = std::exp(result.scores[i][j] - maximum);
            denominator += result.weights[i][j];
        }
        for (int j = 0; j < visible; ++j) {
            double& weight = result.weights[i][j];
            weight /= denominator;
            if (weight > 0) result.entropy[i] -= weight * std::log(weight);
            for (int d = 0; d < data.valueDimensions; ++d)
                result.output[i][d] += weight * data.value[j][d];
        }
    }
    return result;
}

void backward(const Data& data, const Options& config, Result& result) {
    result.queryGradient.assign(data.queries, Vector(data.keyDimensions, 0));
    result.keyGradient.assign(data.keys, Vector(data.keyDimensions, 0));
    result.valueGradient.assign(data.keys, Vector(data.valueDimensions, 0));
    const double scale = 1 / (std::sqrt(static_cast<double>(data.keyDimensions)) * config.temperature);
    for (int i = 0; i < data.queries; ++i) {
        const int visible = config.causal ? i + 1 : data.keys;
        for (int d = 0; d < data.valueDimensions; ++d)
            result.objective += result.output[i][d] * data.upstream[i][d];
        Vector scoreGradient(data.keys, 0);
        // Apply the softmax Jacobian using pairs:
        // D_j = sum_l A_j*A_l*(B_j-B_l), with B=G*V^T.
        // Taking value differences first makes equal values give exactly zero.
        for (int j = 0; j < visible; ++j) {
            for (int l = j + 1; l < visible; ++l) {
                double difference = 0;
                for (int d = 0; d < data.valueDimensions; ++d)
                    difference += data.upstream[i][d] * (data.value[j][d] - data.value[l][d]);
                const double pair = result.weights[i][j] * result.weights[i][l] * difference;
                scoreGradient[j] += pair;
                scoreGradient[l] -= pair;
            }
        }
        for (int j = 0; j < visible; ++j) {
            for (int d = 0; d < data.keyDimensions; ++d) {
                result.queryGradient[i][d] += scale * scoreGradient[j] * data.key[j][d];
                result.keyGradient[j][d] += scale * scoreGradient[j] * data.query[i][d];
            }
            for (int d = 0; d < data.valueDimensions; ++d)
                result.valueGradient[j][d] += result.weights[i][j] * data.upstream[i][d];
        }
    }
}

void array(const Vector& values) {
    std::cout << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << (values[i] == 0 ? 0 : values[i]);
    }
    std::cout << ']';
}

void array(const Matrix& matrix) {
    std::cout << '[';
    for (std::size_t i = 0; i < matrix.size(); ++i) {
        if (i) std::cout << ',';
        array(matrix[i]);
    }
    std::cout << ']';
}

void table(const std::string& label, const Matrix& matrix) {
    std::cout << label << ":\n";
    for (const auto& row : matrix) {
        array(row);
        std::cout << '\n';
    }
}

void report(const Data& data, const Options& config, const Result& result) {
    if (config.json) {
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10)
                  << "{\"query_count\":" << data.queries << ",\"key_count\":" << data.keys
                  << ",\"key_dimensions\":" << data.keyDimensions
                  << ",\"value_dimensions\":" << data.valueDimensions
                  << ",\"temperature\":" << config.temperature
                  << ",\"causal\":" << (config.causal ? "true" : "false") << ",\"query\":";
        array(data.query);
        std::cout << ",\"key\":";
        array(data.key);
        std::cout << ",\"value\":";
        array(data.value);
        std::cout << ",\"scores\":";
        array(result.scores);
        std::cout << ",\"weights\":";
        array(result.weights);
        std::cout << ",\"output\":";
        array(result.output);
        std::cout << ",\"entropy\":";
        array(result.entropy);
        std::cout << ",\"gradients\":";
        if (!config.backward) {
            std::cout << "null";
        } else {
            std::cout << "{\"upstream\":";
            array(data.upstream);
            std::cout << ",\"objective\":" << result.objective << ",\"query\":";
            array(result.queryGradient);
            std::cout << ",\"key\":";
            array(result.keyGradient);
            std::cout << ",\"value\":";
            array(result.valueGradient);
            std::cout << '}';
        }
        std::cout << "}\n";
        return;
    }
    std::cout << std::setprecision(8) << "Scaled dot-product attention: " << data.queries
              << " queries, " << data.keys << " keys\nTemperature: " << config.temperature
              << "\nCausal mask: " << (config.causal ? "on" : "off") << '\n';
    table("Q (queries)", data.query);
    table("K (keys)", data.key);
    table("V (values)", data.value);
    table("Scores Q*K^T / (sqrt(dk)*T), before masking", result.scores);
    table("Weights (each row sums to 1)", result.weights);
    table("Output = weights * V", result.output);
    std::cout << "Row entropy (nats): ";
    array(result.entropy);
    std::cout << '\n';
    if (config.backward) {
        table("G (upstream derivative)", data.upstream);
        std::cout << "Scalar probe L = sum(O * G): " << result.objective << '\n';
        table("dL/dQ", result.queryGradient);
        table("dL/dK", result.keyGradient);
        table("dL/dV", result.valueGradient);
    }
}
}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--help") {
        usage(std::cout);
        return 0;
    }
    try {
        const Options config = options(argc, argv);
        Data data;
        if (config.input.empty()) {
            data = demo();
        } else if (config.input == "-") {
            data = readData(std::cin, config.backward);
        } else {
            std::ifstream input(config.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            data = readData(input, config.backward);
        }
        Result result = attention(data, config);
        if (config.backward) backward(data, config, result);
        report(data, config, result);
    } catch (const std::invalid_argument& error) {
        std::cerr << "Invalid input: " << error.what() << '\n';
        usage(std::cerr);
        return 1;
    }
}
