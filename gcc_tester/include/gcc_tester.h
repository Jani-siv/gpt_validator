// Simple example class header for unit testing
#pragma once

namespace gcc_tester {

class GccTester {
public:
    // returns sum of a and b
    int add(int a, int b) const;

    // returns true if value is even
    bool is_even(int v) const;
};

} // namespace gcc_tester
