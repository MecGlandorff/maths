#include <array>
#include <charconv>
#include <cmath>
#include <complex>
#include <iostream>
#include <string_view>
#include <system_error>

namespace {

constexpr double kTolerance = 1e-6;
constexpr double kMinimumDerivative = 1e-12;
const std::array<std::complex<double>, 3> kRoots = {{
    {1.0, 0.0},
    {-0.5, std::sqrt(3.0) / 2.0},
    {-0.5, -std::sqrt(3.0) / 2.0}
}};

bool parseInteger(const char* text, int minimum, int maximum, int& value) {
    const std::string_view input{text};
    const auto result = std::from_chars(
        input.data(), input.data() + input.size(), value
    );
    return result.ec == std::errc{} &&
           result.ptr == input.data() + input.size() &&
           value >= minimum && value <= maximum;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [width [height [steps]]]\n"
        << "  width: 5..161 (default 81); height: 5..81 (default 41)\n"
        << "  steps: 1..200 Newton updates per point (default 40)\n"
        << "  --help: show this help\n";
}

bool isFinite(const std::complex<double>& value) {
    return std::isfinite(value.real()) && std::isfinite(value.imag());
}

char basinFor(std::complex<double> value, int maximumSteps) {
    for (int step = 0; step <= maximumSteps; ++step) {
        if (!isFinite(value)) {
            return '?';
        }
        for (std::size_t root = 0; root < kRoots.size(); ++root) {
            if (std::abs(value - kRoots[root]) <= kTolerance) {
                return static_cast<char>('1' + root);
            }
        }
        if (step == maximumSteps) {
            break;
        }

        // Newton's update: z <- z - (z^3 - 1) / (3z^2).
        const auto derivative = 3.0 * value * value;
        if (!isFinite(derivative) ||
            std::abs(derivative) <= kMinimumDerivative) {
            return '?';  // In particular, Newton's formula is undefined at 0.
        }
        value -= (value * value * value - 1.0) / derivative;
    }
    return '?';
}

}  // namespace

int main(int argc, char* argv[]) {
    int width = 81;
    int height = 41;
    int steps = 40;
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }
    if (argc > 4 ||
        (argc > 1 && !parseInteger(argv[1], 5, 161, width)) ||
        (argc > 2 && !parseInteger(argv[2], 5, 81, height)) ||
        (argc > 3 && !parseInteger(argv[3], 1, 200, steps))) {
        std::cerr << "Invalid arguments.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::cout << "Newton basins for z^3 = 1 (" << width << " x " << height
              << ", " << steps << " steps)\n"
              << "Window: Re, Im in [-2, 2]; top is +2i.\n"
              << "1 = 1; 2 = -1/2 + sqrt(3)/2 i; 3 = conjugate of 2.\n"
              << "? = unresolved: step limit, tiny derivative, or non-finite value.\n"
              << "Finite-precision approximation: within 1e-6 of a root.\n\n";
    for (int row = 0; row < height; ++row) {
        const double imaginary = 2.0 - 4.0 * row / (height - 1);
        for (int column = 0; column < width; ++column) {
            const double real = -2.0 + 4.0 * column / (width - 1);
            std::cout << basinFor({real, imaginary}, steps);
        }
        std::cout << '\n';
    }
    return 0;
}
