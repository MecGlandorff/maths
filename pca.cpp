#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Vector = std::vector<double>;
using Matrix = std::vector<Vector>;

constexpr int maxSamples = 256;
constexpr int maxFeatures = 8;
constexpr double tolerance = 64 * std::numeric_limits<double>::epsilon();

struct Options {
    bool json = false;
    std::string input;
};

struct Analysis {
    Vector mean;
    Matrix centered;
    Matrix covariance;
    Vector eigenvalues;
    Vector singularValues;
    Matrix axes;  // Each row is a principal direction, in descending variance order.
};

void usage(std::ostream& out) {
    out << "Usage: pca [--input FILE|-] [--json]\n"
           "       pca --help\n"
           "Default: an eight-sample, three-feature demo.\n"
           "Input: n d followed by n*d whitespace-separated numbers.\n"
           "Limits: 2..256 samples, 1..8 features; nonzero magnitudes 1e-100..1e100.\n"
           "Data is centered, without standardizing feature scales.\n";
}

int integer(const std::string& token) {
    int result = 0;
    if (token.empty() || token.front() < '0' || token.front() > '9')
        throw std::invalid_argument("Expected an unsigned integer.");
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size())
        throw std::invalid_argument("Expected an unsigned integer.");
    return result;
}

double number(const std::string& token) {
    // Check decimal/scientific syntax before strtod, which also accepts hex and NaN.
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
        || std::abs(value) > 1e100 || (value != 0 && std::abs(value) < 1e-100))
        throw std::invalid_argument("Value outside the supported numeric range.");
    return value;
}

Options options(int argc, char** argv) {
    Options result;
    bool inputSeen = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--json" && !result.json) {
            result.json = true;
        } else if (arg == "--input" && !inputSeen && i + 1 < argc) {
            inputSeen = true;
            result.input = argv[++i];
            if (result.input.empty()) throw std::invalid_argument("Empty input filename.");
        } else {
            throw std::invalid_argument("Unknown, repeated, or incomplete option.");
        }
    }
    return result;
}

Matrix readData(std::istream& input) {
    std::string nToken, dToken;
    if (!(input >> nToken >> dToken)) throw std::invalid_argument("Missing input dimensions.");
    const int n = integer(nToken), d = integer(dToken);
    if (n < 2 || n > maxSamples || d < 1 || d > maxFeatures)
        throw std::invalid_argument("Input dimensions outside the supported range.");
    Matrix data(n, Vector(d));
    std::string token;
    for (auto& row : data) {
        for (double& value : row) {
            if (!(input >> token)) throw std::invalid_argument("Not enough data values.");
            value = number(token);
        }
    }
    if (input >> token) throw std::invalid_argument("Unexpected trailing input.");
    if (input.bad()) throw std::invalid_argument("Could not read input.");
    return data;
}

Matrix demo() {
    Matrix data;
    for (double u : {-4.0, 4.0})
        for (double v : {-1.0, 1.0})
            for (double w : {-0.25, 0.25})
                data.push_back({10 + u + v, -3 + u - v, 5 + w});
    return data;
}

void eigenvectors(Matrix matrix, Vector& values, Matrix& axes) {
    const int d = static_cast<int>(matrix.size());
    Matrix vectors(d, Vector(d, 0));
    double scale = 0;
    for (int i = 0; i < d; ++i) {
        vectors[i][i] = 1;
        for (double value : matrix[i]) scale = std::max(scale, std::abs(value));
    }
    if (scale != 0)
        for (auto& row : matrix)
            for (double& value : row) value /= scale;

    // Jacobi rotations preserve symmetry and accumulate an orthonormal basis.
    bool converged = false;
    for (int iteration = 0; iteration < 64 * d * d; ++iteration) {
        int p = 0, q = 0;
        double largest = 0;
        for (int i = 0; i < d; ++i)
            for (int j = i + 1; j < d; ++j)
                if (std::abs(matrix[i][j]) > largest) {
                    largest = std::abs(matrix[i][j]);
                    p = i;
                    q = j;
                }
        if (largest <= tolerance) {
            converged = true;
            break;
        }
        const double off = matrix[p][q];
        const double tau = (matrix[q][q] - matrix[p][p]) / (2 * off);
        const double t = std::copysign(1.0, tau) / (std::abs(tau) + std::hypot(1.0, tau));
        const double c = 1 / std::hypot(1.0, t), s = t * c;
        matrix[p][p] -= t * off;
        matrix[q][q] += t * off;
        matrix[p][q] = matrix[q][p] = 0;
        for (int i = 0; i < d; ++i) {
            if (i != p && i != q) {
                const double ip = matrix[i][p], iq = matrix[i][q];
                matrix[i][p] = matrix[p][i] = c * ip - s * iq;
                matrix[i][q] = matrix[q][i] = s * ip + c * iq;
            }
            const double vp = vectors[i][p], vq = vectors[i][q];
            vectors[i][p] = c * vp - s * vq;
            vectors[i][q] = s * vp + c * vq;
        }
    }
    if (!converged) throw std::runtime_error("Jacobi eigensolver did not converge.");
    std::vector<int> order(d);
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return matrix[a][a] > matrix[b][b];
    });
    values.resize(d);
    axes.assign(d, Vector(d));
    for (int j = 0; j < d; ++j) {
        const int index = order[j];
        if (matrix[index][index] < -d * tolerance)
            throw std::runtime_error("Covariance has a negative eigenvalue beyond roundoff.");
        values[j] = std::max(0.0, matrix[index][index]) * scale;
        int pivot = 0;
        for (int i = 0; i < d; ++i) {
            axes[j][i] = vectors[i][index];
            if (std::abs(axes[j][i]) > std::abs(axes[j][pivot])) pivot = i;
        }
        if (axes[j][pivot] < 0)
            for (double& value : axes[j]) value = -value;
    }
}

Analysis analyze(const Matrix& data) {
    const std::size_t n = data.size(), d = data[0].size();
    Analysis result;
    result.mean.assign(d, 0);
    result.centered.assign(n, Vector(d));
    // Average offsets from an anchor: identical samples center to exactly zero.
    for (std::size_t j = 0; j < d; ++j) {
        double offset = 0;
        for (const auto& row : data) offset += (row[j] - data[0][j]) / n;
        result.mean[j] = data[0][j] + offset;
        for (std::size_t i = 0; i < n; ++i)
            result.centered[i][j] = (data[i][j] - data[0][j]) - offset;
    }
    result.covariance.assign(d, Vector(d, 0));
    for (std::size_t j = 0; j < d; ++j)
        for (std::size_t k = j; k < d; ++k) {
            double sum = 0;
            for (const auto& row : result.centered) sum += row[j] * row[k];
            result.covariance[j][k] = result.covariance[k][j] = sum / (n - 1);
        }
    eigenvectors(result.covariance, result.eigenvalues, result.axes);
    for (double value : result.eigenvalues)
        result.singularValues.push_back(std::sqrt((n - 1) * value));
    return result;
}

void array(std::ostream& out, const Vector& values) {
    out << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) out << ',';
        out << (values[i] == 0 ? 0 : values[i]);
    }
    out << ']';
}

void array(std::ostream& out, const Matrix& matrix) {
    out << '[';
    for (std::size_t i = 0; i < matrix.size(); ++i) {
        if (i) out << ',';
        array(out, matrix[i]);
    }
    out << ']';
}

void report(const Analysis& a, bool json) {
    if (json) {
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10)
                  << "{\"samples\":" << a.centered.size()
                  << ",\"features\":" << a.mean.size() << ",\"mean\":";
        array(std::cout, a.mean);
        std::cout << ",\"covariance\":";
        array(std::cout, a.covariance);
        std::cout << ",\"eigenvalues\":";
        array(std::cout, a.eigenvalues);
        std::cout << ",\"singular_values\":";
        array(std::cout, a.singularValues);
        std::cout << ",\"axes\":";
        array(std::cout, a.axes);
        std::cout << "}\n";
        return;
    }
    std::cout << std::setprecision(8)
              << "PCA: " << a.centered.size() << " samples, " << a.mean.size() << " features\n"
              << "Mean: ";
    array(std::cout, a.mean);
    std::cout << "\nSample covariance (centered, divided by n-1):\n";
    for (const auto& row : a.covariance) {
        array(std::cout, row);
        std::cout << '\n';
    }
    std::cout << "Principal directions (largest variance first):\n";
    for (std::size_t j = 0; j < a.mean.size(); ++j) {
        std::cout << "PC" << j + 1 << ": variance=" << a.eigenvalues[j]
                  << " singular value=" << a.singularValues[j] << " axis=";
        array(std::cout, a.axes[j]);
        std::cout << '\n';
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
        Matrix data;
        if (config.input.empty()) {
            data = demo();
        } else if (config.input == "-") {
            data = readData(std::cin);
        } else {
            std::ifstream input(config.input);
            if (!input) throw std::invalid_argument("Could not open input file.");
            data = readData(input);
        }
        report(analyze(data), config.json);
    } catch (const std::invalid_argument& error) {
        std::cerr << "Invalid input: " << error.what() << '\n';
        usage(std::cerr);
        return 1;
    } catch (const std::runtime_error& error) {
        std::cerr << "Numerical error: " << error.what() << '\n';
        return 2;
    }
}
