#include <bitset>
#include <charconv>
#include <iostream>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace {

constexpr int maxSize = 10;
constexpr int maxCells = maxSize * maxSize;
using Pattern = std::bitset<maxCells>;
using Equation = std::bitset<maxCells + 1>;

struct Options {
    int size = 5;
    Pattern board;
    bool showBasis = false;
};

struct Solution {
    bool consistent = true;
    int rank = 0;
    Pattern presses;
    std::vector<Pattern> kernel;
};

struct Minimum {
    Pattern presses;
    unsigned count = 0;
};

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [size [board]] [--basis]\n"
        << "  size: 1..10 (default 5); board: slash-separated rows of 0 and 1\n"
        << "  Without a board, all lights start on. Edges do not wrap.\n"
        << "  Example: " << program << " 3 010/111/010\n"
        << "  --basis: show independent press patterns that leave a board unchanged\n"
        << "  --help: show this help\n";
}

bool parseOptions(int argc, char* argv[], Options& options) {
    int positional = 0;
    std::string_view boardText;
    for (int argument = 1; argument < argc; ++argument) {
        const std::string_view text{argv[argument]};
        if (text == "--basis") {
            if (options.showBasis) return false;
            options.showBasis = true;
        } else if (positional == 0) {
            const auto result = std::from_chars(text.data(), text.data() + text.size(), options.size);
            if (result.ec != std::errc{} || result.ptr != text.data() + text.size()
                || options.size < 1 || options.size > maxSize) {
                return false;
            }
            ++positional;
        } else if (positional == 1) {
            boardText = text;
            ++positional;
        } else {
            return false;
        }
    }

    const int cells = options.size * options.size;
    if (positional < 2) {
        for (int cell = 0; cell < cells; ++cell) {
            options.board.set(cell);
        }
        return true;
    }

    if (boardText.size() != static_cast<std::size_t>(cells + options.size - 1)) {
        return false;
    }
    for (int row = 0; row < options.size; ++row) {
        for (int column = 0; column < options.size; ++column) {
            const char value = boardText[row * (options.size + 1) + column];
            if (value != '0' && value != '1') {
                return false;
            }
            options.board[row * options.size + column] = value == '1';
        }
        if (row + 1 < options.size && boardText[row * (options.size + 1) + options.size] != '/') {
            return false;
        }
    }
    return true;
}

Solution solve(int size, const Pattern& board) {
    const int cells = size * size;
    std::vector<Equation> equations(cells);
    for (int row = 0; row < size; ++row) {
        for (int column = 0; column < size; ++column) {
            const int cell = row * size + column;
            auto& equation = equations[cell];
            equation.set(cell);
            if (row > 0) equation.set(cell - size);
            if (row + 1 < size) equation.set(cell + size);
            if (column > 0) equation.set(cell - 1);
            if (column + 1 < size) equation.set(cell + 1);
            equation[maxCells] = board[cell];
        }
    }

    Solution result;
    std::vector<int> pivots;
    // Addition and subtraction over GF(2) are both XOR. Eliminate above and
    // below every pivot, keeping the right-hand side in the last fixed bit.
    for (int column = 0; column < cells; ++column) {
        int pivot = result.rank;
        while (pivot < cells && !equations[pivot][column]) {
            ++pivot;
        }
        if (pivot == cells) {
            continue;
        }
        std::swap(equations[result.rank], equations[pivot]);
        for (int row = 0; row < cells; ++row) {
            if (row != result.rank && equations[row][column]) {
                equations[row] ^= equations[result.rank];
            }
        }
        pivots.push_back(column);
        ++result.rank;
    }

    for (int row = result.rank; row < cells; ++row) {
        if (equations[row][maxCells]) {
            result.consistent = false; // Zero coefficients with right-hand side 1.
        }
    }
    for (int row = 0; row < result.rank; ++row) {
        result.presses[pivots[row]] = equations[row][maxCells];
    }

    int pivotRow = 0;
    for (int column = 0; column < cells; ++column) {
        if (pivotRow < result.rank && pivots[pivotRow] == column) {
            ++pivotRow;
            continue;
        }
        // Set one free variable to 1, the others to 0, and solve Ax = 0.
        Pattern basis;
        basis.set(column);
        for (int row = 0; row < result.rank; ++row) {
            basis[pivots[row]] = equations[row][column];
        }
        result.kernel.push_back(basis);
    }
    return result;
}

bool rowMajorLess(const Pattern& left, const Pattern& right, int cells) {
    // Bit zero is the top-left cell, whereas bitset::to_string starts at the
    // highest bit. Compare explicitly in reading order, preferring 0 to 1.
    for (int cell = 0; cell < cells; ++cell) {
        if (left[cell] != right[cell]) return !left[cell];
    }
    return false;
}

Minimum findMinimum(const Solution& solution, int cells) {
    Minimum result{solution.presses, 0};
    const unsigned combinations = 1u << solution.kernel.size();
    for (unsigned choice = 0; choice < combinations; ++choice) {
        Pattern presses = solution.presses;
        for (std::size_t basis = 0; basis < solution.kernel.size(); ++basis) {
            if (choice & (1u << basis)) presses ^= solution.kernel[basis];
        }
        if (presses.count() < result.presses.count()) {
            result = {presses, 1};
        } else if (presses.count() == result.presses.count()) {
            ++result.count;
            if (rowMajorLess(presses, result.presses, cells)) result.presses = presses;
        }
    }
    return result;
}

void printPattern(const Pattern& pattern, int size) {
    for (int row = 0; row < size; ++row) {
        std::cout << '|';
        for (int column = 0; column < size; ++column) {
            std::cout << (pattern[row * size + column] ? '1' : '0');
        }
        std::cout << "|\n";
    }
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }
    Options options;
    if (!parseOptions(argc, argv, options)) {
        std::cerr << "Invalid arguments.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    const auto solution = solve(options.size, options.board);
    const int nullity = options.size * options.size - solution.rank;
    // The first press row determines each later row by clearing the row above.
    // There are at most 2^size solutions, hence nullity <= size <= 10.
    const unsigned solutions = solution.consistent ? (1u << nullity) : 0;
    std::cout << "Lights Out: " << options.size << " x " << options.size << '\n'
              << "Input board (1=on, 0=off):\n";
    printPattern(options.board, options.size);
    std::cout << "Rank: " << solution.rank << '\n'
              << "Nullity: " << nullity << '\n'
              << "Solutions: " << solutions << '\n';
    if (!solution.consistent) {
        std::cout << "No solution: row reduction produced 0 = 1.\n";
    } else {
        const auto minimum = findMinimum(solution, options.size * options.size);
        std::cout << "Minimum presses: " << minimum.presses.count() << '\n'
                  << "Minimum solutions: " << minimum.count << '\n'
                  << "Minimum press pattern (1=press, 0=skip):\n";
        printPattern(minimum.presses, options.size);
        std::cout << "Press each marked cell once, in any order.\n";
    }
    if (options.showBasis) {
        std::cout << "Kernel basis: " << solution.kernel.size() << '\n'
                  << "Each basis pattern leaves any board unchanged when pressed.\n";
        for (std::size_t basis = 0; basis < solution.kernel.size(); ++basis) {
            std::cout << "Basis " << basis + 1 << ":\n";
            printPattern(solution.kernel[basis], options.size);
        }
    }
    return solution.consistent ? 0 : 2;
}
