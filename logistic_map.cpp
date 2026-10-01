#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kBurnIn = 1000;
constexpr double kInitialValue = 0.3141592653589793;

bool parseInteger(std::string_view text, int minimum, int maximum, int& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

bool parseRate(const char* text, double& value) {
    // A classic locale keeps the decimal separator predictable. noskipws and
    // eof reject leading/trailing whitespace and partially parsed arguments.
    std::istringstream input{text};
    input.imbue(std::locale::classic());
    input >> std::noskipws >> value;
    return !input.fail() && input.eof() && std::isfinite(value)
           && value >= 0.0 && value <= 4.0;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [r [samples]]\n"
        << "  r: 0..4 (default 3.9); samples: 16..4096 (default 256)\n"
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

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    double rate = 3.9;
    int samples = 256;
    if (argc > 3 || (argc >= 2 && !parseRate(argv[1], rate))
        || (argc == 3 && !parseInteger(argv[2], 16, 4096, samples))) {
        std::cerr << "Invalid arguments.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    const auto orbit = orbitFor(rate, samples);
    std::cout << std::setprecision(12)
              << "Logistic map: x[n+1] = r*x[n]*(1-x[n])\n"
              << "r = " << rate << "; x[0] = " << kInitialValue << '\n'
              << "Discarded updates: " << kBurnIn << "; retained states: " << samples
              << "\nLast 8 retained states:\n"
              << "       n             x[n]\n";
    for (int sample = samples - 8; sample < samples; ++sample) {
        std::cout << std::setw(8) << kBurnIn + sample << "  "
                  << std::fixed << std::setprecision(12) << orbit[sample] << '\n';
    }
    std::cout << "Finite-precision orbit; the discarded updates do not guarantee convergence.\n";
}
