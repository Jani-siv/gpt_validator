#include "gcc_tester.h"

namespace gcc_tester {

int GccTester::add(int a, int b) const {
    return a + b;
}

bool GccTester::is_even(int v) const {
    return (v % 2) == 0;
}

} // namespace gcc_tester
