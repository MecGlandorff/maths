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

struct Parameters {
    Matrix w1;
    Vector b1, w2;
    double b2 = 0;
};

struct Data {
    int samples, features, hiddenUnits;
    Matrix inputs;
    Vector targets;
    Parameters parameters;
};

struct Options {
    std::string input;
    int steps = 0;
    double rate = 1;
    bool trace = false;
    bool json = false;
};

struct TraceEntry {
    int step;
    double loss, parameterGradientNorm;
};

struct Result {
    Matrix hiddenPreactivations, hiddenActivations, hiddenSlopes;
    Vector logits, probabilities, sampleLosses, logitGradients;
    Matrix hiddenGradients, hiddenPreactivationGradients, inputGradients;
    Parameters gradients;
    double loss = 0;
    double parameterGradientNorm = 0;
};

void usage(std::ostream& out) {
    out << "Usage: backpropagation [--input FILE|-] [--steps N] [--rate R] [--trace] [--json]\n"
           "       backpropagation --help\n"
           "Default: a fixed 2-input, 3-hidden-unit network on XOR.\n"
           "Input: n d h, then row-major X (n*d), y (n), W1 (d*h), b1 (h), w2 (h), b2.\n"
           "Limits: n=1..32, d,h=1..8; inputs/initial parameters in [-10,10], y in [0,1].\n"
           "Training: steps=0..5000 (default 0), rate=1e-6..1 (default 1).\n"
           "--trace includes step zero and each completed full-batch update.\n"
           "Reports the mean binary cross-entropy loss and its derivatives.\n";
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
    // Accept decimal/scientific notation, excluding strtod's hex, NaN and infinity forms.
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
    // ERANGE can also mean a representable, nonzero subnormal: retain those values.
    if ((errno == ERANGE && value == 0) || end != token.c_str() + token.size()
        || !std::isfinite(value) || std::abs(value) > 10)
        throw std::invalid_argument("Value outside the supported numeric range.");
    return value;
}

Options options(int argc, char** argv) {
    Options result;
    bool inputSeen = false, stepsSeen = false, rateSeen = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--json" && !result.json) {
            result.json = true;
        } else if (arg == "--trace" && !result.trace) {
            result.trace = true;
        } else if (arg == "--input" && !inputSeen && i + 1 < argc) {
            inputSeen = true;
            result.input = argv[++i];
            if (result.input.empty()) throw std::invalid_argument("Empty input filename.");
        } else if (arg == "--steps" && !stepsSeen && i + 1 < argc) {
            stepsSeen = true;
            result.steps = integer(argv[++i]);
            if (result.steps > 5000) throw std::invalid_argument("Steps must be in 0..5000.");
        } else if (arg == "--rate" && !rateSeen && i + 1 < argc) {
            rateSeen = true;
            result.rate = number(argv[++i]);
            if (result.rate < 1e-6 || result.rate > 1)
                throw std::invalid_argument("Learning rate must be in 1e-6..1.");
        } else {
            throw std::invalid_argument("Unknown, repeated, or incomplete option.");
        }
    }
    return result;
}

Vector readVector(std::istream& input, int count) {
    Vector result(count);
    std::string token;
    for (double& value : result) {
        if (!(input >> token)) throw std::invalid_argument("Not enough input values.");
        value = number(token);
    }
    return result;
}

Matrix readMatrix(std::istream& input, int rows, int columns) {
    Matrix result;
    for (int row = 0; row < rows; ++row) result.push_back(readVector(input, columns));
    return result;
}

Data readData(std::istream& input) {
    std::string n, d, h;
    if (!(input >> n >> d >> h)) throw std::invalid_argument("Missing input dimensions.");
    Data data{integer(n), integer(d), integer(h), {}, {}, {}};
    if (data.samples < 1 || data.samples > 32 || data.features < 1 || data.features > 8
        || data.hiddenUnits < 1 || data.hiddenUnits > 8)
        throw std::invalid_argument("Input dimensions outside the supported range.");
    data.inputs = readMatrix(input, data.samples, data.features);
    data.targets = readVector(input, data.samples);
    for (double target : data.targets)
        if (target < 0 || target > 1) throw std::invalid_argument("Targets must be in [0,1].");
    data.parameters.w1 = readMatrix(input, data.features, data.hiddenUnits);
    data.parameters.b1 = readVector(input, data.hiddenUnits);
    data.parameters.w2 = readVector(input, data.hiddenUnits);
    data.parameters.b2 = readVector(input, 1)[0];
    std::string extra;
    if (input >> extra) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return data;
}

Data demo() {
    return {4, 2, 3, {{-1, -1}, {-1, 1}, {1, -1}, {1, 1}}, {0, 1, 1, 0},
            {{{0.5, -0.7, 0.3}, {-0.4, 0.6, 0.8}}, {0.1, -0.2, 0.05},
             {0.7, -0.5, 0.4}, -0.1}};
}

Result evaluate(const Data& data, const Parameters& parameters) {
    const int n = data.samples, d = data.features, h = data.hiddenUnits;
    Result result;
    result.hiddenPreactivations.assign(n, Vector(h));
    result.hiddenActivations.assign(n, Vector(h));
    result.hiddenSlopes.assign(n, Vector(h));
    result.hiddenGradients.assign(n, Vector(h));
    result.hiddenPreactivationGradients.assign(n, Vector(h));
    result.inputGradients.assign(n, Vector(d));
    result.logits.resize(n);
    result.probabilities.resize(n);
    result.sampleLosses.resize(n);
    result.logitGradients.resize(n);
    result.gradients = {Matrix(d, Vector(h)), Vector(h), Vector(h), 0};
    for (int i = 0; i < n; ++i) {
        double logit = parameters.b2;
        for (int k = 0; k < h; ++k) {
            double z = parameters.b1[k];
            for (int j = 0; j < d; ++j)
                z = std::fma(data.inputs[i][j], parameters.w1[j][k], z);
            result.hiddenPreactivations[i][k] = z;
            const double activation = std::tanh(z);
            result.hiddenActivations[i][k] = activation;
            // 1-tanh(z)^2 loses the derivative once tanh rounds to +/-1.
            const double tail = std::exp(-2 * std::abs(z));
            result.hiddenSlopes[i][k] = 4 * tail / ((1 + tail) * (1 + tail));
            logit = std::fma(activation, parameters.w2[k], logit);
        }
        result.logits[i] = logit;
        const double target = data.targets[i];
        const double tail = std::exp(-std::abs(logit));
        result.probabilities[i] = logit >= 0 ? 1 / (1 + tail) : tail / (1 + tail);
        // BCE and p-y from logits: retain tiny losses/gradients for confident correct labels.
        result.sampleLosses[i] = (logit >= 0 ? (1 - target) * logit : -target * logit)
                                + std::log1p(tail);
        const double numerator = logit >= 0 ? (1 - target) - target * tail
                                            : (1 - target) * tail - target;
        const double delta = numerator / (1 + tail) / n;
        result.logitGradients[i] = delta;
        result.loss += result.sampleLosses[i] / n;
        result.gradients.b2 += delta;
        for (int k = 0; k < h; ++k) {
            result.gradients.w2[k] = std::fma(result.hiddenActivations[i][k], delta,
                                             result.gradients.w2[k]);
            result.hiddenGradients[i][k] = delta * parameters.w2[k];
            const double dz = result.hiddenGradients[i][k] * result.hiddenSlopes[i][k];
            result.hiddenPreactivationGradients[i][k] = dz;
            result.gradients.b1[k] += dz;
            for (int j = 0; j < d; ++j) {
                result.gradients.w1[j][k] = std::fma(data.inputs[i][j], dz,
                                                     result.gradients.w1[j][k]);
                result.inputGradients[i][j] = std::fma(dz, parameters.w1[j][k],
                                                       result.inputGradients[i][j]);
            }
        }
    }
    double norm = std::abs(result.gradients.b2);
    for (const auto& row : result.gradients.w1)
        for (double value : row) norm = std::hypot(norm, value);
    for (double value : result.gradients.b1) norm = std::hypot(norm, value);
    for (double value : result.gradients.w2) norm = std::hypot(norm, value);
    result.parameterGradientNorm = norm;
    return result;
}

void update(Parameters& parameters, const Parameters& gradients, double rate) {
    // Every gradient is from the same pre-update state; inputs and targets stay fixed.
    for (std::size_t j = 0; j < parameters.w1.size(); ++j)
        for (std::size_t k = 0; k < parameters.w1[j].size(); ++k)
            parameters.w1[j][k] = std::fma(-rate, gradients.w1[j][k], parameters.w1[j][k]);
    for (std::size_t k = 0; k < parameters.b1.size(); ++k) {
        parameters.b1[k] = std::fma(-rate, gradients.b1[k], parameters.b1[k]);
        parameters.w2[k] = std::fma(-rate, gradients.w2[k], parameters.w2[k]);
    }
    parameters.b2 = std::fma(-rate, gradients.b2, parameters.b2);
}

void value(double x) {
    std::cout << (x == 0 ? 0 : x);
}

void value(const Vector& values) {
    std::cout << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) std::cout << ',';
        value(values[i]);
    }
    std::cout << ']';
}

void value(const Matrix& matrix) {
    std::cout << '[';
    for (std::size_t i = 0; i < matrix.size(); ++i) {
        if (i) std::cout << ',';
        value(matrix[i]);
    }
    std::cout << ']';
}

void parameterFields(const Parameters& p) {
    std::cout << "\"w1\":";
    value(p.w1);
    std::cout << ",\"b1\":";
    value(p.b1);
    std::cout << ",\"w2\":";
    value(p.w2);
    std::cout << ",\"b2\":";
    value(p.b2);
}

void printJson(const Data& data, const Parameters& parameters, const Result& r,
               const Options& config, double initialLoss, const std::vector<TraceEntry>& trace) {
    std::cout << "{\"samples\":" << data.samples << ",\"features\":" << data.features
              << ",\"hidden_units\":" << data.hiddenUnits << ",\"steps\":" << config.steps
              << ",\"learning_rate\":" << config.rate
              << ",\"initial_loss\":" << initialLoss << ",\"inputs\":";
    value(data.inputs);
    std::cout << ",\"targets\":";
    value(data.targets);
    std::cout << ",\"parameters\":{";
    parameterFields(parameters);
    std::cout << "},\"forward\":{\"hidden_preactivations\":";
    value(r.hiddenPreactivations);
    std::cout << ",\"hidden_activations\":";
    value(r.hiddenActivations);
    std::cout << ",\"hidden_slopes\":";
    value(r.hiddenSlopes);
    std::cout << ",\"logits\":";
    value(r.logits);
    std::cout << ",\"probabilities\":";
    value(r.probabilities);
    std::cout << ",\"sample_losses\":";
    value(r.sampleLosses);
    std::cout << ",\"loss\":";
    value(r.loss);
    std::cout << "},\"backward\":{\"logit_gradients\":";
    value(r.logitGradients);
    std::cout << ",\"hidden_gradients\":";
    value(r.hiddenGradients);
    std::cout << ",\"hidden_preactivation_gradients\":";
    value(r.hiddenPreactivationGradients);
    std::cout << ',';
    parameterFields(r.gradients);
    std::cout << ",\"inputs\":";
    value(r.inputGradients);
    std::cout << ",\"parameter_gradient_norm\":";
    value(r.parameterGradientNorm);
    std::cout << '}';
    if (config.trace) {
        std::cout << ",\"trace\":[";
        for (std::size_t i = 0; i < trace.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << "{\"step\":" << trace[i].step << ",\"loss\":" << trace[i].loss
                      << ",\"parameter_gradient_norm\":" << trace[i].parameterGradientNorm << '}';
        }
        std::cout << ']';
    }
    std::cout << "}\n";
}

template <typename T>
void line(const char* label, const T& x) {
    std::cout << label << ": ";
    value(x);
    std::cout << '\n';
}

void printHuman(const Data& data, const Parameters& parameters, const Result& r,
                const Options& config, double initialLoss, const std::vector<TraceEntry>& trace) {
    std::cout << "Backpropagation: " << data.samples << " samples, " << data.features
              << " inputs, " << data.hiddenUnits << " tanh hidden units, one sigmoid output\n";
    std::cout << "Completed updates: " << config.steps << "; learning rate: " << config.rate << '\n';
    line("Initial loss", initialLoss);
    line("Inputs X", data.inputs);
    line("Targets y", data.targets);
    line("W1", parameters.w1);
    line("b1", parameters.b1);
    line("w2", parameters.w2);
    line("b2", parameters.b2);
    line("Hidden preactivations Z = X W1 + b1", r.hiddenPreactivations);
    line("Hidden activations H = tanh(Z)", r.hiddenActivations);
    line("Hidden slopes dH/dZ", r.hiddenSlopes);
    line("Logits s = H w2 + b2", r.logits);
    line("Probabilities sigmoid(s)", r.probabilities);
    line("Per-sample cross-entropy", r.sampleLosses);
    line("Mean loss L", r.loss);
    line("dL/ds", r.logitGradients);
    line("dL/dH", r.hiddenGradients);
    line("dL/dZ", r.hiddenPreactivationGradients);
    line("dL/dW1", r.gradients.w1);
    line("dL/db1", r.gradients.b1);
    line("dL/dw2", r.gradients.w2);
    line("dL/db2", r.gradients.b2);
    line("dL/dX", r.inputGradients);
    line("Parameter gradient norm", r.parameterGradientNorm);
    if (config.trace) {
        std::cout << "Training trace (step, loss, parameter gradient norm):\n";
        for (const auto& entry : trace)
            std::cout << entry.step << ' ' << entry.loss << ' ' << entry.parameterGradientNorm << '\n';
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
        Data data = demo();
        if (config.input == "-") {
            data = readData(std::cin);
        } else if (!config.input.empty()) {
            std::ifstream input(config.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            data = readData(input);
        }
        Parameters parameters = data.parameters;
        Result result = evaluate(data, parameters);
        const double initialLoss = result.loss;
        std::vector<TraceEntry> trace;
        if (config.trace) trace.push_back({0, result.loss, result.parameterGradientNorm});
        for (int step = 1; step <= config.steps; ++step) {
            update(parameters, result.gradients, config.rate);
            result = evaluate(data, parameters);
            if (config.trace) trace.push_back({step, result.loss, result.parameterGradientNorm});
        }
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10);
        if (config.json) printJson(data, parameters, result, config, initialLoss, trace);
        else printHuman(data, parameters, result, config, initialLoss, trace);
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return 1;
    }
}
