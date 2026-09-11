#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kBarWidth = 40;

bool parseUnsigned(std::string_view text, std::uint32_t& value,
                   std::uint32_t minimum, std::uint32_t maximum) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [rows [balls [seed]]]\n"
        << "Rows: 1-32; balls: 1-1000000; seed: 0-4294967295.\n"
        << "Defaults: 12 rows, 10000 balls, seed 42.\n"
        << "Model: independent fair left/right choices; bin = number of right turns.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    std::uint32_t rows = 12;
    std::uint32_t balls = 10000;
    std::uint32_t seed = 42;
    if (argc > 4 || (argc >= 2 && !parseUnsigned(argv[1], rows, 1, 32))
        || (argc >= 3 && !parseUnsigned(argv[2], balls, 1, 1000000))
        || (argc == 4 && !parseUnsigned(argv[3], seed, 0,
                                      std::numeric_limits<std::uint32_t>::max()))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::vector<std::uint32_t> counts(rows + 1, 0);
    std::mt19937 engine(seed);
    for (std::uint32_t ball = 0; ball < balls; ++ball) {
        std::uint32_t rightTurns = 0;
        for (std::uint32_t row = 0; row < rows; ++row) {
            // Use one high bit per row, with reproducible results across libraries.
            rightTurns += static_cast<std::uint32_t>(engine() >> 31);
        }
        ++counts[rightTurns];
    }

    // P(k) = C(rows, k)/2^rows. Recurrence avoids factorials and overflow;
    // with at most 32 rows, all binomial probabilities fit exactly in double.
    std::vector<double> probabilities(rows + 1);
    probabilities[0] = std::ldexp(1.0, -static_cast<int>(rows));
    for (std::uint32_t bin = 0; bin < rows; ++bin) {
        probabilities[bin + 1] = probabilities[bin] * (rows - bin) / (bin + 1);
    }

    double maximum = *std::max_element(counts.begin(), counts.end());
    for (const double probability : probabilities) {
        maximum = std::max(maximum, balls * probability);
    }
    std::cout << "Galton board: " << rows << " rows, " << balls << " balls, seed " << seed
              << "\nModel: independent 50/50 left/right choices; bin = right turns.\n"
              << "P(bin k) = C(rows, k)/2^rows. Expected = balls * P(k).\n"
              << "# = observed count; | = expected count; all bars share one scale.\n\n"
              << "Bin  Observed    Expected  Probability  Histogram\n";

    double observedMean = 0.0;
    for (std::uint32_t bin = 0; bin <= rows; ++bin) {
        const double expected = balls * probabilities[bin];
        const int observedWidth = static_cast<int>(std::lround(kBarWidth * counts[bin]
                                                              / maximum));
        const int expectedWidth = static_cast<int>(std::lround(kBarWidth * expected
                                                              / maximum));
        std::string bar(kBarWidth + 1, ' ');
        std::fill_n(bar.begin(), observedWidth, '#');
        bar[expectedWidth] = '|';
        std::cout << std::setw(3) << bin << std::setw(10) << counts[bin]
                  << std::fixed << std::setprecision(2) << std::setw(12) << expected
                  << std::scientific << std::setprecision(6) << std::setw(13)
                  << probabilities[bin] << "  [" << bar << "]\n";
        observedMean += static_cast<double>(bin) * counts[bin] / balls;
    }

    std::cout << "\nTotal observed: " << std::accumulate(counts.begin(), counts.end(), 0u)
              << "; total expected: " << balls << '\n'
              << std::fixed << std::setprecision(6) << "Mean bin: observed " << observedMean
              << ", theoretical " << rows / 2.0 << ".\n"
              << "A fixed seed repeats the same pseudorandom experiment; try another seed\n"
              << "to see sampling variation around the exact binomial distribution.\n";
}
