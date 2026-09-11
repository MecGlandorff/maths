#include <array>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>

namespace {

constexpr int kWidth = 81;
constexpr int kHeight = 25;
constexpr int kSamples = 6400;
constexpr double kYLimit = 1.5;  // Includes overshoot, even 4/pi for one term.

bool parseTerms(std::string_view text, int& terms) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), terms);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && terms >= 1 && terms <= 50;
}

double fourierSum(double x, int terms, double pi) {
    double sum = 0.0;
    for (int term = 0; term < terms; ++term) {
        const int harmonic = 2 * term + 1;
        sum += std::sin(harmonic * x) / harmonic;
    }
    return 4.0 * sum / pi;
}

int plotRow(double y) {
    return static_cast<int>(std::lround((kYLimit - y) * (kHeight - 1)
                                       / (2.0 * kYLimit)));
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [terms]\n"
        << "Terms: integer from 1 to 50. Default: 8 odd sine harmonics.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int terms = 8;
    if (argc > 2 || (argc == 2 && !parseTerms(argv[1], terms))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    const double pi = std::acos(-1.0);
    std::array<std::string, kHeight> canvas;
    for (auto& row : canvas) {
        row = std::string(kWidth, ' ');
        row[kWidth / 2] = '|';
    }
    canvas[kHeight / 2] = std::string(kWidth, '-');
    canvas[kHeight / 2][kWidth / 2] = '+';
    for (int column = 1; column < kWidth - 1; ++column) {
        if (column != kWidth / 2) {
            const double target = column < kWidth / 2 ? -1.0 : 1.0;
            canvas[plotRow(target)][column] = '.';
        }
    }

    // Dense samples keep narrow ripples visible between adjacent text columns.
    for (int sample = 0; sample <= kSamples; ++sample) {
        const double fraction = static_cast<double>(sample) / kSamples;
        const double x = (2.0 * fraction - 1.0) * pi;
        const int column = static_cast<int>(std::lround(fraction * (kWidth - 1)));
        canvas[plotRow(fourierSum(x, terms, pi))][column] = '*';
    }

    std::cout << "Fourier square wave: " << terms << " terms, highest harmonic "
              << 2 * terms - 1 << "\n"
              << "S(x) = (4/pi) * [sin(x) + sin(3x)/3 + ...]\n"
              << "* = Fourier sum; . = target; x from -pi to pi, y from -1.5 to 1.5.\n"
              << "Target: -1 on (-pi, 0), +1 on (0, pi), and 0 at the jumps.\n\n";
    const std::string border = "      +" + std::string(kWidth, '-') + "+\n";
    std::cout << border << std::fixed << std::setprecision(1);
    for (int row = 0; row < kHeight; ++row) {
        if (row % 4 == 0) {
            std::cout << std::setw(5) << kYLimit - row * 2.0 * kYLimit / (kHeight - 1);
        } else {
            std::cout << "     ";
        }
        std::cout << " |" << canvas[row] << "|\n";
    }
    std::cout << border << "       -pi" << std::string(37, ' ') << '0'
              << std::string(37, ' ') << "pi\n\n"
              << "  x/pi     Target         S(x)\n" << std::setprecision(6);
    for (const double fraction : {-0.5, -0.1, -0.01, 0.0, 0.01, 0.1, 0.5}) {
        const int target = (fraction > 0.0) - (fraction < 0.0);
        std::cout << std::setw(8) << fraction << std::setw(11) << target
                  << std::setw(13) << fourierSum(fraction * pi, terms, pi) << '\n';
    }

    // Differentiating the finite sum places its first peak at pi/(2*terms).
    const double peakX = pi / (2 * terms);
    const double peak = fourierSum(peakX, terms, pi);
    std::cout << "\nFirst peak: x/pi = " << peakX / pi << ", S(x) = " << peak
              << ", overshoot above +1 = " << peak - 1.0 << ".\n"
              << "Gibbs phenomenon: more terms narrow the ripples, but the overshoot\n"
              << "approaches 0.17898 (about 8.949% of the jump from -1 to +1).\n";
}
