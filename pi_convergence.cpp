#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string_view>
#include <system_error>

namespace {

constexpr int kDefaultUpdates = 10000;
constexpr int kMaximumUpdates = 1000000;

bool parseUpdates(std::string_view text, int& updates) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), updates);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && updates >= 1 && updates <= kMaximumUpdates;
}

void printRow(int updates, long double leibniz, long double nilakantha, long double pi) {
    std::cout << std::setw(8) << updates << "  "
              << std::fixed << std::setprecision(15) << std::setw(18) << leibniz << "  "
              << std::scientific << std::setprecision(3) << std::setw(10) << std::abs(leibniz - pi) << "  "
              << std::fixed << std::setprecision(15) << std::setw(18) << nilakantha << "  "
              << std::scientific << std::setprecision(3) << std::setw(10) << std::abs(nilakantha - pi)
              << '\n';
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [updates from 1 to " << kMaximumUpdates << "]\n"
        << "Default: " << kDefaultUpdates << ". Compares Leibniz and Nilakantha series for pi.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int updates = kDefaultUpdates;
    if (argc > 2 || (argc == 2 && !parseUpdates(argv[1], updates))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    const long double pi = std::acos(-1.0L);
    std::cout << "Pi convergence: Leibniz vs Nilakantha\n"
              << "Library reference: " << std::setprecision(18) << pi << "\n\n"
              << " Updates    Leibniz estimate     |error|     Nilakantha estimate    |error|\n";

    long double leibniz = 0.0L;
    long double nilakantha = 3.0L;
    int checkpoint = 1;
    for (int update = 1; update <= updates; ++update) {
        const long double sign = update % 2 == 1 ? 1.0L : -1.0L;
        leibniz += sign * 4.0L / (2.0L * update - 1.0L);

        // Use floating-point factors before multiplying to avoid integer overflow.
        const long double factor = 2.0L * update;
        nilakantha += sign * 4.0L / (factor * (factor + 1.0L) * (factor + 2.0L));

        if (update == checkpoint || update == updates) {
            printRow(update, leibniz, nilakantha, pi);
            if (update == checkpoint) {
                checkpoint *= 10;
            }
        }
    }

    std::cout << "\nErrors use the finite-precision library reference; rounding eventually limits accuracy.\n";
}
