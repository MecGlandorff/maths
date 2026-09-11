#include <charconv>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <numeric>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

using Integer = std::uint64_t;
constexpr Integer kMaximumPeople = 100;

bool parsePositive(std::string_view text, Integer& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value > 0;
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program << " [people [step]]\n"
        << "People: 1-" << kMaximumPeople << " (default 7). Step: 1-"
        << std::numeric_limits<Integer>::max() << " (default 3).\n"
        << "People are numbered 1..N. Start at person 1 and count them as 1.\n"
        << "Remove every step-th person, then count the next person as 1.\n"
        << "Shows the elimination order and checks the survivor with a recurrence.\n";
}

Integer recurrenceSurvivor(Integer people, Integer step) {
    // Zero-based J(1) = 0; J(n) = (J(n-1) + step) mod n.
    Integer survivor = 0;
    for (Integer size = 2; size <= people; ++size) {
        // Reduce step first, so even the largest accepted step cannot overflow.
        survivor = (survivor + step % size) % size;
    }
    return survivor + 1;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    Integer people = 7;
    Integer step = 3;
    if (argc > 3 || (argc >= 2 && (!parsePositive(argv[1], people)
                                  || people > kMaximumPeople))
        || (argc == 3 && !parsePositive(argv[2], step))) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    std::vector<Integer> circle(static_cast<std::size_t>(people));
    std::iota(circle.begin(), circle.end(), Integer{1});
    std::size_t index = 0;
    std::size_t eliminated = 0;
    std::cout << "Josephus circle: " << people << " people, step " << step << ".\n"
              << "Numbered 1.." << people << "; start at person 1, counting them as 1.\n"
              << "After each removal, count the next person as 1.\nElimination order: ";
    if (people == 1) {
        std::cout << "(none)";
    }

    while (circle.size() > 1) {
        // At most 100 people: reduce the jump before adding it to the index.
        const auto jump = static_cast<std::size_t>((step - 1) % circle.size());
        index = (index + jump) % circle.size();
        if (eliminated != 0) {
            std::cout << (eliminated % 12 == 0 ? "\n -> " : " -> ");
        }
        std::cout << circle[index];
        circle.erase(circle.begin() + static_cast<std::ptrdiff_t>(index));
        ++eliminated;
        // The next person now occupies this index; modulo wraps it next time.
    }

    const Integer expected = recurrenceSurvivor(people, step);
    std::cout << "\nSurvivor: " << circle.front() << '\n';
    if (circle.front() != expected) {
        std::cerr << "Error: simulation disagrees with the independent recurrence.\n";
        return 2;
    }
    std::cout << "Independent recurrence: " << expected << " (matches)\n";
}
