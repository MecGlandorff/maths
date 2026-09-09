#include <algorithm>
#include <charconv>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string_view>
#include <system_error>

namespace {

constexpr std::uint64_t kMaximumSteps = 10000;

bool parsePositive(std::string_view text, std::uint64_t& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value > 0;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [positive-start [max-steps]]\n"
        << "Start must fit in an unsigned 64-bit integer. Default: 27.\n"
        << "Max steps: 1-" << kMaximumSteps << ". Default: " << kMaximumSteps << ".\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    std::uint64_t value = 27;
    std::uint64_t maxSteps = kMaximumSteps;
    if (argc > 3 || (argc >= 2 && !parsePositive(argv[1], value))
        || (argc == 3 && (!parsePositive(argv[2], maxSteps) || maxSteps > kMaximumSteps))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::uint64_t steps = 0;
    std::uint64_t peak = value;
    std::cout << "Collatz sequence starting at " << value << "\n" << value;

    while (value != 1) {
        if (steps == maxSteps) {
            std::cout << '\n';
            std::cerr << "Stopped after " << steps << " steps: limit reached before 1.\n";
            return 2;
        }

        if (value % 2 == 0) {
            value /= 2;
        } else {
            // Check before multiplying: unsigned wraparound would corrupt the sequence.
            if (value > (std::numeric_limits<std::uint64_t>::max() - 1) / 3) {
                std::cout << '\n';
                std::cerr << "Stopped: 3*n+1 would overflow an unsigned 64-bit integer at n="
                          << value << ".\n";
                return 2;
            }
            value = 3 * value + 1;
        }

        ++steps;
        peak = std::max(peak, value);
        std::cout << (steps % 10 == 0 ? "\n -> " : " -> ") << value;
    }

    std::cout << "\n\nSteps to reach 1: " << steps << "\nPeak: " << peak << '\n';
}
