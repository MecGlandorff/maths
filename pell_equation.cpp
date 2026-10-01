#include <charconv>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

using Integer = std::uint64_t;
constexpr Integer kMaximumD = 100;

struct Convergent {
    Integer coefficient;
    Integer numerator;
    Integer denominator;
    Integer residualMagnitude;
    bool positiveResidual;
};

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [D]\n"
        << "D: a nonsquare integer from 2 to " << kMaximumD << " (default 13).\n"
        << "Use continued fractions of sqrt(D) to find the smallest positive\n"
        << "integer solution of x^2 - D*y^2 = 1. Arithmetic is exact.\n"
        << "Shows the repeating coefficients, convergents, and signed Pell residuals.\n";
}

bool parseD(std::string_view text, Integer& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= 2 && value <= kMaximumD;
}

Integer integerSquareRoot(Integer value) {
    // Inputs are at most 100, so these products cannot overflow.
    Integer root = 0;
    while ((root + 1) * (root + 1) <= value) {
        ++root;
    }
    return root;
}

std::vector<Integer> continuedFractionPeriod(Integer value, Integer root) {
    Integer offset = 0;
    Integer divisor = 1;
    Integer coefficient = root;
    std::vector<Integer> period;
    do {
        // Complete quotients have the form (sqrt(D) + offset) / divisor.
        // Their bounded integer parts need no floating-point approximation.
        offset = divisor * coefficient - offset;
        divisor = (value - offset * offset) / divisor;
        coefficient = (root + offset) / divisor;
        period.push_back(coefficient);
    } while (coefficient != 2 * root);
    return period;
}

bool multiplyAdd(Integer factor, Integer value, Integer addend, Integer& result) {
    if (factor != 0 && value > (std::numeric_limits<Integer>::max() - addend) / factor) {
        return false;
    }
    result = factor * value + addend;
    return true;
}

bool findSolution(Integer value, Integer root, const std::vector<Integer>& period,
                  std::vector<Convergent>& convergents) {
    Integer previousNumerator = 1;
    Integer olderNumerator = 0;
    Integer previousDenominator = 0;
    Integer olderDenominator = 1;

    // A positive Pell solution occurs within two periods, counting a_0.
    for (std::size_t index = 0; index < 2 * period.size(); ++index) {
        const Integer coefficient = index == 0 ? root : period[(index - 1) % period.size()];
        Integer numerator = 0;
        Integer denominator = 0;
        Integer numeratorSquared = 0;
        Integer denominatorSquared = 0;
        Integer scaledDenominatorSquared = 0;
        if (!multiplyAdd(coefficient, previousNumerator, olderNumerator, numerator)
            || !multiplyAdd(coefficient, previousDenominator, olderDenominator, denominator)
            || !multiplyAdd(numerator, numerator, 0, numeratorSquared)
            || !multiplyAdd(denominator, denominator, 0, denominatorSquared)
            || !multiplyAdd(value, denominatorSquared, 0, scaledDenominatorSquared)) {
            return false;
        }

        const bool positive = numeratorSquared > scaledDenominatorSquared;
        const Integer magnitude = positive ? numeratorSquared - scaledDenominatorSquared
                                           : scaledDenominatorSquared - numeratorSquared;
        convergents.push_back({coefficient, numerator, denominator, magnitude, positive});
        if (positive && magnitude == 1) {
            return true;
        }
        olderNumerator = previousNumerator;
        previousNumerator = numerator;
        olderDenominator = previousDenominator;
        previousDenominator = denominator;
    }
    return false;
}

void printExploration(Integer value, Integer root, const std::vector<Integer>& period,
                      const std::vector<Convergent>& convergents) {
    std::cout << "sqrt(" << value << ") = [" << root << "; (";
    for (std::size_t index = 0; index < period.size(); ++index) {
        std::cout << (index == 0 ? "" : ", ") << period[index];
    }
    std::cout << ")]\nParentheses repeat. Period length: " << period.size() << ".\n"
              << "An even period needs L convergents; an odd period needs 2L.\n\n"
              << "Convergents p/q approach sqrt(D) from below and above:\n"
              << std::setw(3) << "n" << std::setw(5) << "a_n"
              << std::setw(14) << "p" << std::setw(14) << "q"
              << std::setw(17) << "p^2 - D*q^2" << "  side\n";
    for (std::size_t index = 0; index < convergents.size(); ++index) {
        const auto& row = convergents[index];
        const std::string residual = (row.positiveResidual ? "+" : "-")
                                     + std::to_string(row.residualMagnitude);
        std::cout << std::setw(3) << index << std::setw(5) << row.coefficient
                  << std::setw(14) << row.numerator << std::setw(14) << row.denominator
                  << std::setw(17) << residual
                  << (row.positiveResidual ? "  above" : "  below") << '\n';
    }
    std::cout << "\nThe first +1 residual gives the smallest positive Pell solution.\n"
              << "A -1 residual solves the companion equation x^2 - D*y^2 = -1.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    Integer value = 13;
    if (argc > 2 || (argc == 2 && !parseD(argv[1], value))) {
        usage(std::cerr, argv[0]);
        return 1;
    }
    const Integer root = integerSquareRoot(value);
    if (root * root == value) {
        std::cerr << "D must not be a perfect square.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    const auto period = continuedFractionPeriod(value, root);
    std::vector<Convergent> convergents;
    if (!findSolution(value, root, period, convergents)) {
        std::cerr << "Stopped: exact 64-bit arithmetic or the two-period limit was exceeded.\n";
        return 2;
    }

    std::cout << "Pell equation: x^2 - " << value << "*y^2 = 1\n";
    printExploration(value, root, period, convergents);
    const auto& solution = convergents.back();
    std::cout << "Smallest positive solution: x = " << solution.numerator
              << ", y = " << solution.denominator << '\n'
              << solution.numerator << "^2 - " << value << "*"
              << solution.denominator << "^2 = 1\n";
}
