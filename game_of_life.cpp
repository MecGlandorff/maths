#include <algorithm>
#include <charconv>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

using Grid = std::vector<std::string>;

bool parseInteger(const char* text, int minimum, int maximum, int& value) {
    const std::string_view input{text};
    const auto result = std::from_chars(
        input.data(), input.data() + input.size(), value
    );
    return result.ec == std::errc{} &&
           result.ptr == input.data() + input.size() &&
           value >= minimum && value <= maximum;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program
        << " [seed [generations [width [height]]]]\n"
        << "  seed: glider (default) or blinker\n"
        << "  generations: 0..50 updates (default 8); initial board is also shown\n"
        << "  width: 5..80 (default 20); height: 5..40 (default 12)\n"
        << "  Outside cells stay dead; edges do not wrap.\n"
        << "  --help: show this help\n";
}

Grid makeSeed(std::string_view seed, int width, int height) {
    Grid grid(height, std::string(width, '.'));
    const int top = height / 2 - 1;
    const int left = width / 2 - 1;
    if (seed == "blinker") {
        for (int column = left; column < left + 3; ++column) {
            grid[top + 1][column] = '#';
        }
    } else {
        // .#.    This glider moves one cell down and right every four updates
        // ..#    while it is away from the fixed, dead exterior.
        // ###
        grid[top][left + 1] = '#';
        grid[top + 1][left + 2] = '#';
        for (int column = left; column < left + 3; ++column) {
            grid[top + 2][column] = '#';
        }
    }
    return grid;
}

Grid nextGeneration(const Grid& grid) {
    const int height = static_cast<int>(grid.size());
    const int width = static_cast<int>(grid.front().size());
    Grid next(height, std::string(width, '.'));
    for (int row = 0; row < height; ++row) {
        for (int column = 0; column < width; ++column) {
            int neighbors = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    const int y = row + dy;
                    const int x = column + dx;
                    if ((dy != 0 || dx != 0) &&
                        y >= 0 && y < height && x >= 0 && x < width &&
                        grid[y][x] == '#') {
                        ++neighbors;
                    }
                }
            }
            // B3/S23: birth with 3 neighbors; survival with 2 or 3.
            if (neighbors == 3 || (grid[row][column] == '#' && neighbors == 2)) {
                next[row][column] = '#';
            }
        }
    }
    return next;
}

void printGrid(const Grid& grid, int generation) {
    std::size_t population = 0;
    for (const auto& row : grid) {
        population += static_cast<std::size_t>(
            std::count(row.begin(), row.end(), '#')
        );
    }
    const std::string border = '+' + std::string(grid.front().size(), '-') + '+';
    std::cout << "Generation " << generation << " (" << population << " live)\n"
              << border << '\n';
    for (const auto& row : grid) {
        std::cout << '|' << row << "|\n";
    }
    std::cout << border << "\n\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    std::string_view seed = "glider";
    int generations = 8;
    int width = 20;
    int height = 12;
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }
    if (argc > 1) {
        seed = argv[1];
    }
    if (argc > 5 || (seed != "glider" && seed != "blinker") ||
        (argc > 2 && !parseInteger(argv[2], 0, 50, generations)) ||
        (argc > 3 && !parseInteger(argv[3], 5, 80, width)) ||
        (argc > 4 && !parseInteger(argv[4], 5, 40, height))) {
        std::cerr << "Invalid arguments.\n";
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::cout << "Conway's Game of Life (seed=" << seed << ", " << width
              << " x " << height << ")\n"
              << "B3/S23; outside the board stays dead (no wrapping).\n"
              << "# = live; . = dead\n\n";
    auto grid = makeSeed(seed, width, height);
    for (int generation = 0; generation <= generations; ++generation) {
        printGrid(grid, generation);
        if (generation < generations) {
            grid = nextGeneration(grid);
        }
    }
    return 0;
}
