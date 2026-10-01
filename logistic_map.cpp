#include <algorithm>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kBurnIn = 1000;
constexpr double kInitialValue = 0.3141592653589793;
constexpr double kMinimumPlotRate = 2.5;
constexpr double kMaximumPlotRate = 4.0;

bool parseInteger(std::string_view text, int minimum, int maximum, int& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

bool parseRate(const char* text, double& value) {
    // Restrict the syntax to decimal/scientific notation: some standard
    // libraries also accept hexadecimal input when extracting a double.
    if (std::string_view{text}.find_first_not_of("0123456789+-.eE")
        != std::string_view::npos) {
        return false;
    }
    // A classic locale keeps the decimal separator predictable. noskipws and
    // eof reject leading/trailing whitespace and partially parsed arguments.
    std::istringstream input{text};
    input.imbue(std::locale::classic());
    input >> std::noskipws >> value;
    return !input.fail() && input.eof() && std::isfinite(value)
           && value >= 0.0 && value <= 4.0;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [r [samples [width [height]]]]\n"
        << "  r: 0..4 (default 3.9); samples: 16..4096 (default 256)\n"
        << "  width: 21..161 (default 81); height: 11..61 (default 25)\n"
        << "  r selects the orbit report; the diagram always spans r = 2.5..4.0.\n"
        << "  Discards the first 1000 updates; uses a fixed starting value.\n"
        << "  --help: show this help\n";
}

std::vector<double> orbitFor(double rate, int samples) {
    double value = kInitialValue;
    for (int step = 0; step < kBurnIn; ++step) {
        value = rate * value * (1.0 - value);
    }

    std::vector<double> orbit;
    orbit.reserve(samples);
    for (int sample = 0; sample < samples; ++sample) {
        orbit.push_back(value);
        value = rate * value * (1.0 - value);
    }
    return orbit;
}

double lyapunovEstimate(double rate, const std::vector<double>& orbit) {
    double total = 0.0;
    for (const double value : orbit) {
        const double derivativeMagnitude = std::abs(rate * (1.0 - 2.0 * value));
        if (derivativeMagnitude == 0.0) {
            return -std::numeric_limits<double>::infinity();
        }
        total += std::log(derivativeMagnitude);
    }
    return total / static_cast<double>(orbit.size());
}

void drawBifurcations(int width, int height, int samples) {
    std::vector<std::string> canvas(height, std::string(width, ' '));
    for (int column = 0; column < width; ++column) {
        const double rate = kMinimumPlotRate
                            + (kMaximumPlotRate - kMinimumPlotRate) * column / (width - 1);
        for (const double value : orbitFor(rate, samples)) {
            const int row = std::clamp(
                static_cast<int>(std::lround((1.0 - value) * (height - 1))), 0, height - 1);
            canvas[row][column] = '*';
        }
    }

    std::cout << "\nBifurcation diagram: * marks a sampled state; columns vary r.\n"
              << "   x\n";
    for (int row = 0; row < height; ++row) {
        const double value = 1.0 - static_cast<double>(row) / (height - 1);
        std::cout << std::fixed << std::setprecision(2) << std::setw(4) << value
                  << " |" << canvas[row] << "|\n";
    }
    std::cout << "     +" << std::string(width, '-') << "+\n"
              << "      2.5" << std::string(width - 6, ' ') << "4.0   r\n"
              << "The diagram uses the same start, discarded updates, and sample count\n"
              << "at every column. Narrow features may fall between columns.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    double rate = 3.9;
    int samples = 256;
    int width = 81;
    int height = 25;
    if (argc > 5 || (argc >= 2 && !parseRate(argv[1], rate))
        || (argc >= 3 && !parseInteger(argv[2], 16, 4096, samples))
        || (argc >= 4 && !parseInteger(argv[3], 21, 161, width))
        || (argc >= 5 && !parseInteger(argv[4], 11, 61, height))) {
        std::cerr << "Invalid arguments.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    const auto orbit = orbitFor(rate, samples);
    std::cout << std::setprecision(12)
              << "Logistic map: x[n+1] = r*x[n]*(1-x[n])\n"
              << "r = " << rate << "; x[0] = " << kInitialValue << '\n'
              << "Discarded updates: " << kBurnIn << "; retained states: " << samples
              << '\n';
    drawBifurcations(width, height, samples);
    std::cout << "\nSelected r = " << std::setprecision(12) << rate
              << "\nLast 8 retained states:\n"
              << "       n             x[n]\n";
    for (int sample = samples - 8; sample < samples; ++sample) {
        std::cout << std::setw(8) << kBurnIn + sample << "  "
                  << std::fixed << std::setprecision(12) << orbit[sample] << '\n';
    }
    const double exponent = lyapunovEstimate(rate, orbit);
    std::cout << "Finite-time Lyapunov estimate: ";
    if (std::isinf(exponent)) {
        std::cout << "-inf (a sampled derivative is zero)\n";
    } else {
        std::cout << std::setprecision(9) << exponent << '\n';
    }
    std::cout << "Mean of ln(|r*(1-2*x)|) over the retained states.\n"
              << "Its sign describes average local expansion (+) or contraction (-)\n"
              << "along this finite orbit. Finite precision and sampling limit the result;\n"
              << "the discarded updates do not guarantee convergence.\n";
}
