#include <cmath>
#include <complex>
#include <cstddef>
#include <iostream>
#include <string_view>

namespace {

constexpr int kWidth = 96;
constexpr int kHeight = 32;
constexpr int kMaxIterations = 80;

int escapeIterations(const std::complex<double>& point) {
    std::complex<double> value{0.0, 0.0};
    int iterations = 0;

    while (std::norm(value) <= 4.0 && iterations < kMaxIterations) {
        value = value * value + point;
        ++iterations;
    }

    return iterations;
}

char shadeFor(int iterations) {
    constexpr std::string_view shades = " .:-=+*#%";

    if (iterations == kMaxIterations) {
        return '@';
    }

    const double progress = std::sqrt(
        static_cast<double>(iterations) / kMaxIterations
    );
    const auto index = static_cast<std::size_t>(
        progress * static_cast<double>(shades.size() - 1)
    );
    return shades[index];
}

double scale(int position, int size, double minimum, double maximum) {
    const double fraction = static_cast<double>(position) / (size - 1);
    return minimum + fraction * (maximum - minimum);
}

}  // namespace

int main() {
    constexpr double kMinReal = -2.2;
    constexpr double kMaxReal = 1.0;
    constexpr double kMinImaginary = -1.2;
    constexpr double kMaxImaginary = 1.2;

    std::cout << "ASCII Mandelbrot set\n\n";

    for (int row = 0; row < kHeight; ++row) {
        const double imaginary = scale(
            row, kHeight, kMaxImaginary, kMinImaginary
        );

        for (int column = 0; column < kWidth; ++column) {
            const double real = scale(
                column, kWidth, kMinReal, kMaxReal
            );
            const std::complex<double> point{real, imaginary};
            std::cout << shadeFor(escapeIterations(point));
        }

        std::cout << '\n';
    }

    return 0;
}
