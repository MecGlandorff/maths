#include <charconv>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>

namespace {

constexpr std::uint32_t kMaximumTarget = 40;
constexpr int kBarWidth = 30;

struct Theory {
    long double successProbability;
    long double expectedSteps;
};

bool parseUnsigned(std::string_view text, std::uint32_t& value,
                   std::uint32_t minimum, std::uint32_t maximum) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

Theory theoreticalResult(std::uint32_t start, std::uint32_t target,
                         std::uint32_t winPercent) {
    if (start == 0) {
        return {0.0L, 0.0L};
    }
    if (start == target) {
        return {1.0L, 0.0L};
    }
    if (winPercent == 0) {
        return {0.0L, static_cast<long double>(start)};
    }
    if (winPercent == 100) {
        return {1.0L, static_cast<long double>(target - start)};
    }
    if (winPercent == 50) {
        return {static_cast<long double>(start) / target,
                static_cast<long double>(start) * (target - start)};
    }

    const long double p = winPercent / 100.0L;
    const long double q = 1.0L - p;
    long double probability;
    if (p < q) {
        // Rescale (1-r^start)/(1-r^target), r=q/p, to avoid large powers.
        const long double logRatio = std::log(p / q);
        probability = std::exp((target - start) * logRatio)
                      * std::expm1(start * logRatio)
                      / std::expm1(target * logRatio);
    } else {
        const long double logRatio = std::log(q / p);
        probability = std::expm1(start * logRatio) / std::expm1(target * logRatio);
    }
    return {probability, (start - target * probability) / (q - p)};
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [start [target [win-percent]]]\n"
        << "Target: 2-40; start: 0-target; win-percent: 0-100.\n"
        << "Defaults: start 10, target 20, win-percent 50.\n"
        << "Model: independent +1/-1 steps, stopping at 0 or the target.\n";
}

void printTheory(std::uint32_t start, std::uint32_t target, std::uint32_t winPercent) {
    std::cout << "Gambler's ruin: start " << start << ", target " << target
              << ", win probability " << winPercent << "% per step.\n"
              << "Stop at 0 (ruin) or the target (success).\n"
              << "Exact model formulas, evaluated in floating-point arithmetic.\n\n"
              << "Start        P(target)       E(steps)  Success probability\n";
    for (std::uint32_t capital = 0; capital <= target; ++capital) {
        const Theory result = theoreticalResult(capital, target, winPercent);
        const int filled = static_cast<int>(std::lround(result.successProbability
                                                       * kBarWidth));
        std::cout << std::setw(5) << capital << "  " << std::scientific
                  << std::setprecision(8) << std::setw(15) << result.successProbability
                  << "  " << std::fixed << std::setprecision(6) << std::setw(13)
                  << result.expectedSteps << "  [" << std::string(filled, '#')
                  << std::string(kBarWidth - filled, ' ') << ']'
                  << (capital == start ? " < selected" : "") << '\n';
    }
    const Theory selected = theoreticalResult(start, target, winPercent);
    std::cout << "\nTheoretical success probability: " << std::scientific
              << std::setprecision(10) << selected.successProbability
              << "\nTheoretical expected steps: " << std::fixed << std::setprecision(6)
              << selected.expectedSteps << '\n';
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    std::uint32_t start = 10;
    std::uint32_t target = 20;
    std::uint32_t winPercent = 50;
    if (argc > 4 || (argc >= 2 && !parseUnsigned(argv[1], start, 0, kMaximumTarget))
        || (argc >= 3 && !parseUnsigned(argv[2], target, 2, kMaximumTarget))
        || (argc == 4 && !parseUnsigned(argv[3], winPercent, 0, 100)) || start > target) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    printTheory(start, target, winPercent);
}
