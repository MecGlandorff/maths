#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Vector = std::vector<double>;

Vector readVector(const std::string& line) {
    std::istringstream input(line);
    Vector values;
    std::string token;
    while (input >> token) {
        char* end = nullptr;
        errno = 0;
        const double value = std::strtod(token.c_str(), &end);
        if (end == token.c_str() || end != token.c_str() + token.size()
            || !std::isfinite(value) || (errno == ERANGE && value == 0))
            throw std::runtime_error("Invalid number: " + token);
        values.push_back(value);
    }
    return values;
}

void normalize(Vector& values) {
    double scale = 0;
    for (double value : values) scale = std::max(scale, std::abs(value));
    if (scale == 0) throw std::runtime_error("A zero vector has no direction.");

    // Scaling first avoids overflow when finding the length.
    double length = 0;
    for (double& value : values) {
        value /= scale;
        length = std::hypot(length, value);
    }
    for (double& value : values) value /= length;
}

struct Match {
    std::size_t number;
    double score;
};

int main(int argc, char**) {
    if (argc != 1) {
        std::cerr << "Usage: cosine_search < vectors.txt\n";
        return 1;
    }
    try {
        Vector query;
        std::vector<Match> matches;
        std::string line;
        while (std::getline(std::cin, line)) {
            Vector candidate = readVector(line);
            if (candidate.empty()) continue;
            if (query.empty()) {
                normalize(candidate);
                query = candidate;
                continue;
            }
            if (candidate.size() != query.size())
                throw std::runtime_error("All vectors must have the same dimension.");
            normalize(candidate);
            double score = 0;
            for (std::size_t i = 0; i < query.size(); ++i)
                score += query[i] * candidate[i];
            matches.push_back({matches.size() + 1, std::clamp(score, -1.0, 1.0)});
        }
        if (std::cin.bad()) throw std::runtime_error("Could not read input.");
        if (matches.empty()) throw std::runtime_error("Provide a query and at least one candidate.");

        std::stable_sort(matches.begin(), matches.end(), [](const Match& a, const Match& b) {
            return a.score > b.score;
        });
        std::cout << std::fixed << std::setprecision(6);
        for (const Match& match : matches)
            std::cout << match.number << ' ' << match.score << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
