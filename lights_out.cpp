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
};

struct Solution {
    bool consistent = true;
    int rank = 0;
    Pattern presses;
};

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [size [board]]\n"
        << "  size: 1..10 (default 5); board: slash-separated rows of 0 and 1\n"
        << "  Without a board, all lights start on. Edges do not wrap.\n"
        << "  Example: " << program << " 3 010/111/010\n"
        << "  --help: show this help\n";
}

bool parseOptions(int argc, char* argv[], Options& options) {
    if (argc > 3) {
        return false;
    }
    if (argc >= 2) {
        const std::string_view text{argv[1]};
        const auto result = std::from_chars(text.data(), text.data() + text.size(), options.size);
        if (result.ec != std::errc{} || result.ptr != text.data() + text.size()
            || options.size < 1 || options.size > maxSize) {
            return false;
        }
    }

    const int cells = options.size * options.size;
    if (argc < 3) {
        for (int cell = 0; cell < cells; ++cell) {
            options.board.set(cell);
        }
        return true;
    }

    const std::string_view text{argv[2]};
    if (text.size() != static_cast<std::size_t>(cells + options.size - 1)) {
        return false;
    }
    for (int row = 0; row < options.size; ++row) {
        for (int column = 0; column < options.size; ++column) {
            const char value = text[row * (options.size + 1) + column];
            if (value != '0' && value != '1') {
                return false;
            }
            options.board[row * options.size + column] = value == '1';
        }
        if (row + 1 < options.size && text[row * (options.size + 1) + options.size] != '/') {
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
        return 2;
    }
    std::cout << "One press pattern (1=press, 0=skip):\n";
    printPattern(solution.presses, options.size);
    return 0;
}
