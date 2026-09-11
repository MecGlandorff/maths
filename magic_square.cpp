#include <charconv>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kDefaultSize = 5;
constexpr int kMaximumSize = 25;

bool parseSize(std::string_view text, int& size) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), size);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && size >= 1 && size <= kMaximumSize && size % 2 == 1;
}

std::vector<std::vector<int>> makeSquare(int size) {
    std::vector<std::vector<int>> square(size, std::vector<int>(size, 0));
    int row = 0;
    int column = size / 2;

    // Siamese method: move up/right with wraparound; if occupied, move down.
    for (int value = 1; value <= size * size; ++value) {
        square[row][column] = value;
        const int nextRow = (row + size - 1) % size;
        const int nextColumn = (column + 1) % size;
        if (square[nextRow][nextColumn] != 0) {
            row = (row + 1) % size;
        } else {
            row = nextRow;
            column = nextColumn;
        }
    }
    return square;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [odd size from 1 to " << kMaximumSize << "]\n"
        << "Default: " << kDefaultSize << ". Builds a square using every integer from 1 to size^2.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int size = kDefaultSize;
    if (argc > 2 || (argc == 2 && !parseSize(argv[1], size))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    const auto square = makeSquare(size);
    const int magicSum = size * (size * size + 1) / 2;
    const int cellWidth = static_cast<int>(std::to_string(size * size).size()) + 1;
    const std::string border = "+" + std::string(size * cellWidth, '-') + "+\n";
    std::cout << "Magic square (" << size << " x " << size << ")\n"
              << "Magic sum: " << magicSum << " (every row, column and both main diagonals)\n\n"
              << border;
    for (const auto& row : square) {
        std::cout << '|';
        for (const int value : row) {
            std::cout << std::setw(cellWidth) << value;
        }
        std::cout << "|\n";
    }
    std::cout << border;
}
