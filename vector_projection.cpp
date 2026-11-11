#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>

// Input: ax ay bx by. Project vector a onto the direction of b
// For 3 4 1 1, the projection is (3.5, 3.5) and the remainder is (-0.5, 0.5)
int main() {
    std::array<double, 2> a, b;
    if (!(std::cin >> a[0] >> a[1] >> b[0] >> b[1])) {
        std::cerr << "Enter four numbers: ax ay bx by \n";
        return 1;
    }
    std::string extra;
    if ((std::cin >> extra) || std::cin.bad()
        || !std::isfinite(a[0]) || !std::isfinite(a[1])
        || !std::isfinite(b[0]) || !std::isfinite(b[1])) {
        std::cerr << "Expected exactly four finite numbers. \n";
        return 1;
    }

    const double bScale = std::max(std::abs(b[0]), std::abs(b[1]));
    if (bScale == 0) {
        std::cerr << "The direction vector cannot be zero. \n";
        return 1;
    }

    // Scale first, so finding lengths and dot products does not overflow
    for (double& value : b) value /= bScale;
    const double length = std::hypot(b[0], b[1]);
    for (double& value : b) value /= length;
    double aScale = std::max(std::abs(a[0]), std::abs(a[1]));
    if (aScale == 0) aScale = 1;
    for (double& value : a) value /= aScale;

    const double along = a[0] * b[0] + a[1] * b[1];
    // (-b.y, b.x) is perpendicular to the unit direction b 
    const double across = -a[0] * b[1] + a[1] * b[0];
    const std::array<double, 2> projection = {along * b[0] * aScale, along * b[1] * aScale};
    const std::array<double, 2> remainder = {-across * b[1] * aScale, across * b[0] * aScale};
    for (int i = 0; i < 2; ++i) {
        if (!std::isfinite(projection[i]) || !std::isfinite(remainder[i])) {
            std::cerr << "The result is too large to represent.\n";
            return 1;
        }
    }

    std::cout << std::setprecision(10)
              << "Projection: " << projection[0] << ' ' << projection[1] << '\n'
              << "Remainder: " << remainder[0] << ' ' << remainder[1] << '\n';
}
