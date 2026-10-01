#include <charconv>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace {

constexpr std::uint32_t kMaximumTarget = 40;
constexpr std::uint32_t kMaximumTrials = 10000;
constexpr std::uint32_t kMaximumSteps = 10000;
constexpr std::uint32_t kPathUpdates = 60;
constexpr int kBarWidth = 30;

struct Theory {
    long double successProbability;
    long double expectedSteps;
};

struct Experiment {
    std::uint32_t successes = 0;
    std::uint32_t ruins = 0;
    std::uint32_t unresolved = 0;
    std::uint64_t observedSteps = 0;
    std::vector<std::uint32_t> samplePath;
    std::uint32_t sampleSteps = 0;
    std::uint32_t sampleFinal = 0;
};

bool parseUnsigned(std::string_view text, std::uint32_t& value,
                   std::uint32_t minimum, std::uint32_t maximum) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size()
           && value >= minimum && value <= maximum;
}

Theory theoreticalResult(std::uint32_t start, std::uint32_t target,
                         std::uint32_t winPercent) {
    if (start == 0) {
        return {0.0L, 0.0L};
    }
    if (start == target) {
        return {1.0L, 0.0L};
    }
    if (winPercent == 0) {
        return {0.0L, static_cast<long double>(start)};
    }
    if (winPercent == 100) {
        return {1.0L, static_cast<long double>(target - start)};
    }
    if (winPercent == 50) {
        return {static_cast<long double>(start) / target,
                static_cast<long double>(start) * (target - start)};
    }

    const long double p = winPercent / 100.0L;
    const long double q = 1.0L - p;
    long double probability;
    if (p < q) {
        // Rescale (1-r^start)/(1-r^target), r=q/p, to avoid large powers.
        const long double logRatio = std::log(p / q);
        probability = std::exp((target - start) * logRatio)
                      * std::expm1(start * logRatio)
                      / std::expm1(target * logRatio);
    } else {
        const long double logRatio = std::log(q / p);
        probability = std::expm1(start * logRatio) / std::expm1(target * logRatio);
    }
    return {probability, (start - target * probability) / (q - p)};
}

void usage(std::ostream& out, const char* program) {
    out << "Usage: " << program
        << " [start [target [win-percent [trials [seed [step-limit]]]]]]\n"
        << "Target: 2-40; start: 0-target; win-percent: 0-100.\n"
        << "Trials: 1-10000; seed: 0-4294967295; step-limit per trial: 1-10000.\n"
        << "Defaults: start 10, target 20, win-percent 50, trials 10000, seed 42,\n"
        << "          step-limit 10000. Each trial stops at 0 or the target.\n"
        << "Independent +1/-1 steps; exit 2 if any trial reaches its step limit\n"
        << "without absorption. Unresolved trials remain separate from losses.\n";
}

void printTheory(std::uint32_t start, std::uint32_t target, std::uint32_t winPercent) {
    std::cout << "Gambler's ruin: start " << start << ", target " << target
              << ", win probability " << winPercent << "% per step.\n"
              << "Stop at 0 (ruin) or the target (success).\n"
              << "Exact model formulas, evaluated in floating-point arithmetic.\n\n"
              << "Start        P(target)       E(steps)  Success probability\n";
    for (std::uint32_t capital = 0; capital <= target; ++capital) {
        const Theory result = theoreticalResult(capital, target, winPercent);
        const int filled = static_cast<int>(std::lround(result.successProbability
                                                       * kBarWidth));
        std::cout << std::setw(5) << capital << "  " << std::scientific
                  << std::setprecision(8) << std::setw(15) << result.successProbability
                  << "  " << std::fixed << std::setprecision(6) << std::setw(13)
                  << result.expectedSteps << "  [" << std::string(filled, '#')
                  << std::string(kBarWidth - filled, ' ') << ']'
                  << (capital == start ? " < selected" : "") << '\n';
    }
    const Theory selected = theoreticalResult(start, target, winPercent);
    std::cout << "\nTheoretical success probability: " << std::scientific
              << std::setprecision(10) << selected.successProbability
              << "\nTheoretical expected steps: " << std::fixed << std::setprecision(6)
              << selected.expectedSteps << '\n';
}

bool winningStep(std::mt19937& engine, std::uint32_t winPercent) {
    if (winPercent == 0 || winPercent == 100) {
        return winPercent == 100;
    }
    // Reject the excess values before reducing modulo 100: no modulo bias,
    // and no library-specific distribution algorithm changes seeded results.
    constexpr std::uint64_t range = std::uint64_t{1} << 32;
    constexpr std::uint64_t limit = range - range % 100;
    std::uint32_t draw;
    do {
        draw = static_cast<std::uint32_t>(engine());
    } while (draw >= limit);
    return draw % 100 < winPercent;
}

Experiment simulate(std::uint32_t start, std::uint32_t target,
                    std::uint32_t winPercent, std::uint32_t trials,
                    std::uint32_t seed, std::uint32_t stepLimit) {
    Experiment experiment;
    experiment.samplePath.push_back(start);
    std::mt19937 engine(seed);
    for (std::uint32_t trial = 0; trial < trials; ++trial) {
        std::uint32_t capital = start;
        std::uint32_t steps = 0;
        while (capital != 0 && capital != target && steps < stepLimit) {
            if (winningStep(engine, winPercent)) {
                ++capital;
            } else {
                --capital;
            }
            ++steps;
            if (trial == 0 && steps <= kPathUpdates) {
                experiment.samplePath.push_back(capital);
            }
        }
        experiment.observedSteps += steps;
        if (capital == target) {
            ++experiment.successes;
        } else if (capital == 0) {
            ++experiment.ruins;
        } else {
            ++experiment.unresolved;
        }
        if (trial == 0) {
            experiment.sampleSteps = steps;
            experiment.sampleFinal = capital;
        }
    }
    return experiment;
}

void printSamplePath(const Experiment& experiment, std::uint32_t target) {
    std::cout << "\nSample path (first trial; * = bankroll at each update)\nOutcome: ";
    if (experiment.sampleFinal == target) {
        std::cout << "target";
    } else if (experiment.sampleFinal == 0) {
        std::cout << "ruin";
    } else {
        std::cout << "unresolved (per-trial step limit)";
    }
    std::cout << " after " << experiment.sampleSteps << " update"
              << (experiment.sampleSteps == 1 ? ".\n" : "s.\n");
    const auto& path = experiment.samplePath;
    if (experiment.sampleSteps > kPathUpdates) {
        std::cout << "Showing updates 0-" << kPathUpdates << "; remaining "
                  << experiment.sampleSteps - kPathUpdates << " updates omitted.\n";
    }
    for (int capital = static_cast<int>(target); capital >= 0; --capital) {
        std::cout << std::setw(3) << capital << " |";
        for (const std::uint32_t position : path) {
            std::cout << (position == static_cast<std::uint32_t>(capital) ? '*' : ' ');
        }
        std::cout << '|' << (capital == 0 ? " ruin" : "")
                  << (capital == static_cast<int>(target) ? " target" : "") << '\n';
    }
    std::cout << "    +" << std::string(path.size(), '-') << "+\n";
    std::string labels(path.size() + 1, ' ');
    for (std::size_t step = 0; step < path.size(); step += 10) {
        labels.replace(step, std::to_string(step).size(), std::to_string(step));
    }
    std::cout << "     " << labels << "  update\n";
}

void printExperiment(const Experiment& experiment, std::uint32_t trials,
                     std::uint32_t seed, std::uint32_t stepLimit) {
    const long double meanObserved = static_cast<long double>(experiment.observedSteps)
                                     / trials;
    std::cout << "\nSimulation: " << trials << " trials, seed " << seed
              << ", step limit " << stepLimit << " per trial.\n"
              << "Successes: " << experiment.successes << "\nRuins: " << experiment.ruins
              << "\nUnresolved: " << experiment.unresolved << '\n'
              << std::fixed << std::setprecision(6);
    if (experiment.unresolved == 0) {
        std::cout << "Observed success fraction: "
                  << static_cast<long double>(experiment.successes) / trials
                  << "\nObserved mean steps: " << meanObserved << '\n';
    } else {
        const long double lower = static_cast<long double>(experiment.successes) / trials;
        const long double upper = static_cast<long double>(experiment.successes
                                                           + experiment.unresolved)
                                  / trials;
        std::cout << "Unresolved trials are neither successes nor ruins.\n"
                  << "Eventual success fraction for this batch lies in ["
                  << experiment.successes << '/' << trials << ", "
                  << experiment.successes + experiment.unresolved << '/' << trials
                  << "].\nApproximate bounds: [" << lower << ", " << upper
                  << "]; these describe unresolved outcomes, not a confidence interval.\n"
                  << "Observed mean min(T, step-limit): " << meanObserved << '\n'
                  << "Durations are censored; this is not an estimate of the full mean T.\n";
    }
    std::cout << "The same arguments reproduce the experiment across runs.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        usage(std::cout, argv[0]);
        return 0;
    }

    std::uint32_t start = 10;
    std::uint32_t target = 20;
    std::uint32_t winPercent = 50;
    std::uint32_t trials = 10000;
    std::uint32_t seed = 42;
    std::uint32_t stepLimit = 10000;
    if (argc > 7 || (argc >= 2 && !parseUnsigned(argv[1], start, 0, kMaximumTarget))
        || (argc >= 3 && !parseUnsigned(argv[2], target, 2, kMaximumTarget))
        || (argc >= 4 && !parseUnsigned(argv[3], winPercent, 0, 100))
        || (argc >= 5 && !parseUnsigned(argv[4], trials, 1, kMaximumTrials))
        || (argc >= 6 && !parseUnsigned(argv[5], seed, 0,
                                      std::numeric_limits<std::uint32_t>::max()))
        || (argc == 7 && !parseUnsigned(argv[6], stepLimit, 1, kMaximumSteps))
        || start > target) {
        usage(std::cerr, argv[0]);
        return 1;
    }

    printTheory(start, target, winPercent);
    const Experiment experiment = simulate(start, target, winPercent, trials, seed,
                                           stepLimit);
    printExperiment(experiment, trials, seed, stepLimit);
    printSamplePath(experiment, target);
    return experiment.unresolved == 0 ? 0 : 2;
}
