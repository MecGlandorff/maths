#include <array>
#include <charconv>
#include <cstdint>
#include <deque>
#include <iostream>
#include <numeric>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

using Count = std::uint64_t;

struct Options {
    int size = 31;
    Count grains = 10000;
    bool showOdometer = false;
};

struct Sandpile {
    std::vector<Count> heights;
    std::vector<Count> odometer;
    Count lost = 0;
    Count topplings = 0;
};

bool parseUnsigned(std::string_view text, Count minimum, Count maximum, Count& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [size [grains]] [--odometer]\n"
        << "  size: odd, 3..61 (default 31); grains: 0..100000 (default 10000)\n"
        << "  All grains start at the center; grains crossing an edge are lost.\n"
        << "  --odometer: append exact toppling counts for every cell\n"
        << "  --help: show this help\n";
}

bool parseOptions(int argc, char* argv[], Options& options) {
    int positional = 0;
    for (int argument = 1; argument < argc; ++argument) {
        const std::string_view text{argv[argument]};
        if (text == "--odometer") {
            if (options.showOdometer) {
                return false;
            }
            options.showOdometer = true;
        } else if (positional == 0) {
            Count size = 0;
            if (!parseUnsigned(text, 3, 61, size) || size % 2 == 0) {
                return false;
            }
            options.size = static_cast<int>(size);
            ++positional;
        } else if (positional == 1) {
            if (!parseUnsigned(text, 0, 100000, options.grains)) {
                return false;
            }
            ++positional;
        } else {
            return false;
        }
    }
    return true;
}

Sandpile stabilize(int size, Count grains) {
    const int cells = size * size;
    Sandpile pile{std::vector<Count>(cells, 0), std::vector<Count>(cells, 0)};
    const int center = (size / 2) * size + size / 2;
    pile.heights[center] = grains;
    std::deque<int> pending;
    std::vector<bool> queued(cells, false);
    const auto schedule = [&](int cell) {
        if (pile.heights[cell] >= 4 && !queued[cell]) {
            pending.push_back(cell);
            queued[cell] = true;
        }
    };
    schedule(center);

    constexpr std::array<int, 4> rowOffsets = {-1, 1, 0, 0};
    constexpr std::array<int, 4> columnOffsets = {0, 0, -1, 1};
    // Weight (r+1)*(size-r) + (c+1)*(size-c) drops by at least 4 per
    // toppling, including boundary loss. Thus there are at most
    // grains*(size+1)^2/8 individual topplings: <= 48,050,000 here.
    // Every height is <= grains; all exact counts fit comfortably in Count.
    while (!pending.empty()) {
        const int cell = pending.front();
        pending.pop_front();
        queued[cell] = false;
        const Count batch = pile.heights[cell] / 4;
        pile.heights[cell] %= 4;
        pile.odometer[cell] += batch;
        pile.topplings += batch;

        // This batch is equivalent to that many consecutive legal topplings
        // at this cell; each move sends one grain in each orthogonal direction.
        const int row = cell / size;
        const int column = cell % size;
        for (int direction = 0; direction < 4; ++direction) {
            const int nextRow = row + rowOffsets[direction];
            const int nextColumn = column + columnOffsets[direction];
            if (nextRow < 0 || nextRow >= size || nextColumn < 0 || nextColumn >= size) {
                pile.lost += batch;
            } else {
                const int neighbor = nextRow * size + nextColumn;
                pile.heights[neighbor] += batch;
                schedule(neighbor);
            }
        }
    }
    return pile;
}

void printHeights(const Sandpile& pile, int size) {
    const std::string border = '+' + std::string(size, '-') + '+';
    std::cout << "\nFinal heights (grains per cell, 0..3):\n" << border << '\n';
    for (int row = 0; row < size; ++row) {
        std::cout << '|';
        for (int column = 0; column < size; ++column) {
            std::cout << pile.heights[row * size + column];
        }
        std::cout << "|\n";
    }
    std::cout << border << '\n';
}

void printOdometer(const Sandpile& pile, int size) {
    // Coordinate records keep even the largest grid's exact output narrow.
    std::cout << "\nExact odometer (all cells; row and column are zero-based):\n"
              << "row column topplings\n";
    for (int row = 0; row < size; ++row) {
        for (int column = 0; column < size; ++column) {
            std::cout << row << ' ' << column << ' '
                      << pile.odometer[row * size + column] << '\n';
        }
    }
}

}  // namespace

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

    const auto pile = stabilize(options.size, options.grains);
    const Count retained = std::accumulate(pile.heights.begin(), pile.heights.end(), Count{0});
    std::cout << "Abelian sandpile: " << options.size << " x " << options.size
              << "; grains initially at the center.\n"
              << "A cell with at least 4 grains sends one to each orthogonal neighbor.\n"
              << "Open absorbing edges: grains leaving the grid are lost.\n"
              << "Initial grains: " << options.grains << '\n'
              << "Retained grains: " << retained << '\n'
              << "Lost grains: " << pile.lost << '\n'
              << "Total topplings: " << pile.topplings << '\n';
    printHeights(pile, options.size);
    if (options.showOdometer) {
        printOdometer(pile, options.size);
    }
}
