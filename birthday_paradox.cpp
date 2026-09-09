#include <algorithm>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr int kDays = 365;
constexpr int kBarWidth = 40;

bool parsePeople(std::string_view text, int& people) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), people);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && people >= 0 && people <= kDays + 1;
}

double sharedBirthdayProbability(int people) {
    if (people > kDays) {
        return 1.0;
    }

    // First compute the complement: every birthday is different.
    double allDifferent = 1.0;
    for (int person = 1; person < people; ++person) {
        allDifferent *= static_cast<double>(kDays - person) / kDays;
    }
    return 1.0 - allDifferent;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [people from 0 to " << kDays + 1 << "]\n"
        << "Default: 23 people. Assumes independent, equally likely birthdays on 365 days.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    int people = 23;
    if (argc > 2 || (argc == 2 && !parsePeople(argv[1], people))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::vector<int> groups{0, 2, 5, 10, 15, 20, 23, 30, 40, 50, 60, 100, 366, people};
    std::sort(groups.begin(), groups.end());
    groups.erase(std::unique(groups.begin(), groups.end()), groups.end());

    std::cout << "Birthday paradox\n"
              << "Model: 365 equally likely days, independent birthdays, no leap day.\n\n"
              << "People  P(at least one shared birthday)\n"
              << std::fixed << std::setprecision(6);
    for (const int group : groups) {
        const double probability = sharedBirthdayProbability(group);
        const int filled = static_cast<int>(std::lround(probability * kBarWidth));
        std::cout << std::setw(6) << group << "  " << std::setw(10) << probability * 100.0
                  << "% [" << std::string(filled, '#')
                  << std::string(kBarWidth - filled, ' ') << ']'
                  << (group == people ? " < selected" : "") << '\n';
    }

    int threshold = 0;
    while (sharedBirthdayProbability(threshold) < 0.5) {
        ++threshold;
    }
    std::cout << "\nFirst group with at least 50% probability: " << threshold << " people.\n";
}
