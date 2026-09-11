#include <charconv>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <numeric>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

using Integer = std::uint64_t;
constexpr Integer kMaximumInput = 1000000;
constexpr std::size_t kMaximumTerms = 32;

bool parseInput(std::string_view text, Integer& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value <= kMaximumInput;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [numerator denominator]\n"
        << "Default: 4/13. Numerator: 0-" << kMaximumInput
        << "; denominator: 1-" << kMaximumInput << ".\n"
        << "Greedily choose the largest unit fraction that fits the remainder.\n"
        << "Whole parts stay as integers; zero gives 0. Unit fractions are distinct.\n"
        << "Uses exact 64-bit integers; stops with an exact remainder before overflow\n"
        << "or after " << kMaximumTerms << " unit fractions (exit status 2).\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    Integer numerator = 4;
    Integer denominator = 13;
    if ((argc != 1 && argc != 3)
        || (argc == 3 && (!parseInput(argv[1], numerator)
                         || !parseInput(argv[2], denominator) || denominator == 0))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    const Integer inputNumerator = numerator;
    const Integer inputDenominator = denominator;
    const Integer inputGcd = std::gcd(numerator, denominator);
    numerator /= inputGcd;
    denominator /= inputGcd;
    std::cout << "Greedy Egyptian fractions\n"
              << "Reduced input: " << numerator << '/' << denominator << '\n';

    const Integer whole = numerator / denominator;
    numerator %= denominator;
    std::vector<Integer> unitDenominators;
    const char* stopReason = nullptr;

    while (numerator != 0) {
        if (unitDenominators.size() == kMaximumTerms) {
            stopReason = "unit-fraction limit reached";
            break;
        }

        // ceil(d/n), without overflowing by adding n-1 to d.
        const Integer unit = denominator / numerator + (denominator % numerator != 0);
        const Integer common = std::gcd(denominator, unit);
        const Integer factor = unit / common;

        // Use lcm(d, unit) as the next denominator. Since n < d, this also
        // guarantees that n * factor fits. Stop before changing the remainder.
        if (denominator > std::numeric_limits<Integer>::max() / factor) {
            stopReason = "the next intermediate denominator would overflow 64 bits";
            break;
        }
        numerator = numerator * factor - denominator / common;
        denominator *= factor;
        const Integer divisor = std::gcd(numerator, denominator);
        numerator /= divisor;
        denominator /= divisor;
        unitDenominators.push_back(unit);
    }

    std::cout << inputNumerator << '/' << inputDenominator << " = ";
    bool haveTerm = false;
    if (whole != 0) {
        std::cout << whole;
        haveTerm = true;
    }
    for (const Integer unit : unitDenominators) {
        std::cout << (haveTerm ? " + " : "") << "1/" << unit;
        haveTerm = true;
    }
    if (numerator != 0) {
        std::cout << (haveTerm ? " + " : "") << '(' << numerator << '/'
                  << denominator << " remaining)";
    } else if (!haveTerm) {
        std::cout << '0';
    }
    std::cout << "\nUnit fractions: " << unitDenominators.size() << '\n';
    if (stopReason != nullptr) {
        std::cerr << "Stopped: " << stopReason
                  << ". The displayed remainder is exact.\n";
        return 2;
    }
}
