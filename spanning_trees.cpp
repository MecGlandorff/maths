#include <algorithm>
#include <charconv>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace {

using Count = std::int64_t;
using Matrix = std::vector<std::vector<Count>>;
using Edge = std::pair<int, int>;

struct Graph {
    int vertices = 0;
    std::vector<Edge> edges;
};

struct Options {
    std::string_view family = "grid";
    int size = 3;
    Graph graph;
    bool showEdgeStats = false;
};

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [family [size [edges]]] [--edge-stats]\n"
        << "  family: path, cycle, complete, grid, custom (default grid)\n"
        << "  size: vertices 1..10; cycle needs 3..10; grid side 1..3 (default 3)\n"
        << "  custom requires size and edges, e.g. custom 4 0-1,1-2,2-3\n"
        << "  Use - for no edges. Loops and duplicate edges are invalid.\n"
        << "  --edge-stats: exact edge inclusion counts, probabilities, and bridges\n"
        << "  --help: show this help\n";
}

bool parseInteger(std::string_view text, int minimum, int maximum, int& value) {
    if (text.empty() || text.front() < '0' || text.front() > '9') return false;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

bool parseEdges(std::string_view text, Graph& graph) {
    if (text == "-") return true;
    std::size_t start = 0;
    while (true) {
        const auto comma = text.find(',', start);
        const auto token = text.substr(start, comma == std::string_view::npos
                                                ? text.size() - start : comma - start);
        const auto dash = token.find('-');
        int left = 0;
        int right = 0;
        if (dash == std::string_view::npos
            || !parseInteger(token.substr(0, dash), 0, graph.vertices - 1, left)
            || !parseInteger(token.substr(dash + 1), 0, graph.vertices - 1, right)
            || left == right) {
            return false;
        }
        if (left > right) std::swap(left, right);
        const Edge edge{left, right};
        if (std::find(graph.edges.begin(), graph.edges.end(), edge) != graph.edges.end()) {
            return false;
        }
        graph.edges.push_back(edge);
        if (comma == std::string_view::npos) break;
        start = comma + 1;
        if (start == text.size()) return false;
    }
    return true;
}

bool parseOptions(int argc, char* argv[], Options& options) {
    std::vector<std::string_view> positional;
    for (int argument = 1; argument < argc; ++argument) {
        const std::string_view text{argv[argument]};
        if (text == "--edge-stats") {
            if (options.showEdgeStats) return false;
            options.showEdgeStats = true;
        } else {
            positional.push_back(text);
        }
    }
    if (positional.size() > 3) return false;
    if (!positional.empty()) options.family = positional[0];
    if (options.family != "path" && options.family != "cycle"
        && options.family != "complete" && options.family != "grid"
        && options.family != "custom") {
        return false;
    }
    const int minimum = options.family == "cycle" ? 3 : 1;
    const int maximum = options.family == "grid" ? 3 : 10;
    if (positional.size() >= 2 && !parseInteger(positional[1], minimum, maximum, options.size)) {
        return false;
    }
    auto& graph = options.graph;
    graph.vertices = options.family == "grid" ? options.size * options.size : options.size;
    if (options.family == "custom") {
        if (positional.size() != 3 || !parseEdges(positional[2], graph)) return false;
    } else {
        if (positional.size() > 2) return false;
        if (options.family == "path" || options.family == "cycle") {
            for (int vertex = 1; vertex < graph.vertices; ++vertex) {
                graph.edges.emplace_back(vertex - 1, vertex);
            }
            if (options.family == "cycle") graph.edges.emplace_back(0, graph.vertices - 1);
        } else if (options.family == "complete") {
            for (int left = 0; left < graph.vertices; ++left) {
                for (int right = left + 1; right < graph.vertices; ++right) {
                    graph.edges.emplace_back(left, right);
                }
            }
        } else {
            for (int row = 0; row < options.size; ++row) {
                for (int column = 0; column < options.size; ++column) {
                    const int vertex = row * options.size + column;
                    if (column + 1 < options.size) graph.edges.emplace_back(vertex, vertex + 1);
                    if (row + 1 < options.size) graph.edges.emplace_back(vertex, vertex + options.size);
                }
            }
        }
    }
    std::sort(graph.edges.begin(), graph.edges.end());
    return true;
}

Matrix laplacian(const Graph& graph) {
    Matrix result(graph.vertices, std::vector<Count>(graph.vertices, 0));
    for (const auto& edge : graph.edges) {
        const auto [left, right] = edge;
        ++result[left][left];
        ++result[right][right];
        --result[left][right];
        --result[right][left];
    }
    return result;
}

Matrix principalMinor(const Matrix& matrix, int first, int second = -1) {
    Matrix result;
    const int size = static_cast<int>(matrix.size());
    for (int row = 0; row < size; ++row) {
        if (row == first || row == second) continue;
        std::vector<Count> values;
        for (int column = 0; column < size; ++column) {
            if (column != first && column != second) values.push_back(matrix[row][column]);
        }
        result.push_back(std::move(values));
    }
    return result;
}

Count determinant(Matrix matrix) {
    const int size = static_cast<int>(matrix.size());
    if (size == 0) return 1;
    Count previous = 1;
    // Fraction-free Bareiss elimination: stored entries are minors, and each
    // division by the previous pivot is exact. Every input here is a principal
    // Laplacian minor, hence positive semidefinite. A zero pivot implies a
    // singular matrix; no row swaps are needed for these specific matrices.
    // For simple graphs with <=10 vertices, Laplacian row norms are <10.
    // Hadamard bounds every relevant minor by 10^9, so each difference of two
    // products is <2*10^18, safely inside signed 64-bit arithmetic.
    for (int pivotIndex = 0; pivotIndex + 1 < size; ++pivotIndex) {
        const Count pivot = matrix[pivotIndex][pivotIndex];
        if (pivot == 0) return 0;
        for (int row = pivotIndex + 1; row < size; ++row) {
            for (int column = pivotIndex + 1; column < size; ++column) {
                const Count numerator = matrix[row][column] * pivot
                                        - matrix[row][pivotIndex] * matrix[pivotIndex][column];
                matrix[row][column] = numerator / previous;
            }
            matrix[row][pivotIndex] = 0;
        }
        previous = pivot;
    }
    return matrix.back().back();
}

void printMatrix(const Matrix& matrix) {
    if (matrix.empty()) std::cout << "Empty matrix: determinant 1.\n";
    for (const auto& row : matrix) {
        std::cout << '|';
        for (Count value : row) std::cout << ' ' << value;
        std::cout << " |\n";
    }
}

void printEdgeStatistics(const Graph& graph, const Matrix& matrix, Count trees) {
    Count sum = 0;
    std::cout << "Edge inclusion (uniform spanning tree):\n"
              << "u v trees probability bridge\n";
    for (const auto& edge : graph.edges) {
        const auto [left, right] = edge;
        // Contract this unit edge and delete the merged vertex. The resulting
        // cofactor is the original Laplacian with both endpoints removed.
        // Original degrees retain the multiplicities of contracted edges.
        const Count containing = determinant(principalMinor(matrix, left, right));
        const Count divisor = std::gcd(containing, trees);
        std::cout << left << ' ' << right << ' ' << containing << ' '
                  << containing / divisor << '/' << trees / divisor << ' '
                  << (containing == trees ? "yes" : "no") << '\n';
        sum += containing;
    }
    std::cout << "Inclusion sum: " << sum << '\n';
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
    const auto matrix = laplacian(options.graph);
    const auto cofactor = principalMinor(matrix, options.graph.vertices - 1);
    const Count trees = determinant(cofactor);
    std::cout << "Spanning trees: " << options.family << " (size " << options.size << ")\n"
              << "Vertices: " << options.graph.vertices << '\n'
              << "Edges: " << options.graph.edges.size() << '\n'
              << "Trees: " << trees << '\n'
              << "Cofactor (remove vertex " << options.graph.vertices - 1 << "):\n";
    printMatrix(cofactor);
    if (trees == 0) {
        std::cout << "No spanning tree: graph is disconnected.\n";
        return 2;
    }
    if (options.showEdgeStats) printEdgeStatistics(options.graph, matrix, trees);
    return 0;
}
