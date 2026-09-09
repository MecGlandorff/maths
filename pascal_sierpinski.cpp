#include <charconv>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>

namespace {

constexpr int kDefaultRows = 32;
constexpr int kMaximumRows = 64;

bool parseRows(std::string_view text, int& rows) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), rows);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && rows >= 1 && rows <= kMaximumRows;
}

bool isOddCoefficient(int row, int column) {
    // C(row, column) is odd exactly when adding column and row-column
    // in binary requires no carries. No factorials or large integers needed.
    return (column & (row - column)) == 0;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [rows from 1 to " << kMaximumRows << "]\n"
        << "Default: " << kDefaultRows << " rows. * = odd Pascal coefficient.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int rows = kDefaultRows;
    if (argc > 2 || (argc == 2 && !parseRows(argv[1], rows))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::cout << "Pascal / Sierpinski triangle (" << rows << " rows)\n"
              << "* = odd coefficient; spaces = even coefficients\n\n";
    for (int row = 0; row < rows; ++row) {
        std::cout << std::string(rows - row - 1, ' ');
        for (int column = 0; column <= row; ++column) {
            if (column != 0) {
                std::cout << ' ';
            }
            std::cout << (isOddCoefficient(row, column) ? '*' : ' ');
        }
        std::cout << '\n';
    }
}
