#include <charconv>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kDefaultSize = 31;
constexpr int kMinimumSize = 5;
constexpr int kMaximumSize = 99;

constexpr bool isPrime(int value) {
    if (value < 2) {
        return false;
    }
    if (value % 2 == 0) {
        return value == 2;
    }

    for (int divisor = 3; divisor <= value / divisor; divisor += 2) {
        if (value % divisor == 0) {
            return false;
        }
    }

    return true;
}

static_assert(!isPrime(1));
static_assert(isPrime(2));
static_assert(isPrime(29));
static_assert(!isPrime(49));

bool parseSize(const char* text, int& size) {
    const std::string_view input{text};
    const auto result = std::from_chars(
        input.data(), input.data() + input.size(), size
    );

    return result.ec == std::errc{} &&
           result.ptr == input.data() + input.size() &&
           size >= kMinimumSize && size <= kMaximumSize && size % 2 == 1;
}

std::vector<int> makeSpiral(int size) {
    std::vector<int> grid(size * size, 0);
    constexpr int rowChange[] = {0, -1, 0, 1};
    constexpr int columnChange[] = {1, 0, -1, 0};

    int row = size / 2;
    int column = size / 2;
    int value = 1;
    int direction = 0;
    int runLength = 1;
    const int maximum = size * size;
    grid[row * size + column] = value++;

    while (value <= maximum) {
        for (int turn = 0; turn < 2 && value <= maximum; ++turn) {
            for (int step = 0; step < runLength && value <= maximum; ++step) {
                row += rowChange[direction];
                column += columnChange[direction];
                grid[row * size + column] = value++;
            }
            direction = (direction + 1) % 4;
        }
        ++runLength;
    }

    return grid;
}

void printSpiral(const std::vector<int>& grid, int size) {
    std::cout << '+' << std::string(size * 2, '-') << "+\n";

    for (int row = 0; row < size; ++row) {
        std::cout << '|';
        for (int column = 0; column < size; ++column) {
            const int value = grid[row * size + column];
            if (value == 1) {
                std::cout << "<>";
            } else {
                std::cout << (isPrime(value) ? "##" : "  ");
            }
        }
        std::cout << "|\n";
    }

    std::cout << '+' << std::string(size * 2, '-') << "+\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    int size = kDefaultSize;

    if (argc > 2 || (argc == 2 && !parseSize(argv[1], size))) {
        std::cerr << "Usage: " << argv[0]
                  << " [odd size from " << kMinimumSize
                  << " to " << kMaximumSize << "]\n";
        return 1;
    }

    std::cout << "Ulam prime spiral (" << size << " x " << size << ")\n"
              << "## = prime, <> = center\n\n";
    printSpiral(makeSpiral(size), size);

    return 0;
}
