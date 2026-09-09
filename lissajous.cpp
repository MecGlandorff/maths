#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <iostream>
#include <numeric>
#include <string>
#include <string_view>
#include <system_error>

namespace {

constexpr int kWidth = 81;
constexpr int kHeight = 33;
constexpr int kSamples = 12000;

bool parseFrequency(std::string_view text, int& frequency) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), frequency);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && frequency >= 1 && frequency <= 9;
}

int coordinate(double value, int extent) {
    const int pixel = static_cast<int>(std::lround((value + 1.0) * 0.5 * (extent - 1)));
    return std::clamp(pixel, 0, extent - 1);
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [x-frequency y-frequency]\n"
        << "Frequencies: integers from 1 to 9. Default: 3 2.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int frequencyX = 3;
    int frequencyY = 2;
    if ((argc != 1 && argc != 3)
        || (argc == 3 && (!parseFrequency(argv[1], frequencyX)
                         || !parseFrequency(argv[2], frequencyY)))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::array<std::string, kHeight> canvas;
    for (auto& row : canvas) {
        row = std::string(kWidth, ' ');
        row[kWidth / 2] = '|';
    }
    canvas[kHeight / 2] = std::string(kWidth, '-');
    canvas[kHeight / 2][kWidth / 2] = '+';

    // Integer frequencies repeat after this common period.
    const double period = 2.0 * std::acos(-1.0) / std::gcd(frequencyX, frequencyY);
    for (int sample = 0; sample < kSamples; ++sample) {
        const double time = period * sample / kSamples;
        const double x = std::cos(frequencyX * time);
        const double y = std::sin(frequencyY * time);
        canvas[coordinate(-y, kHeight)][coordinate(x, kWidth)] = '*';
    }

    std::cout << "ASCII Lissajous curve (x:y = " << frequencyX << ':' << frequencyY << ")\n"
              << "* = curve; - and | = axes\n\n";
    const std::string border = "+" + std::string(kWidth, '-') + "+\n";
    std::cout << border;
    for (const auto& row : canvas) {
        std::cout << '|' << row << "|\n";
    }
    std::cout << border;
}
