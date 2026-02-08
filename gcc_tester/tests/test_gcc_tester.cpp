#include "gtest/gtest.h"
#include "gcc_tester.h"
#include <fstream>

using namespace gcc_tester;

TEST(GccTesterBasic, AddWorks) {
    GccTester t;
    EXPECT_EQ(t.add(1, 2), 3);
    EXPECT_EQ(t.add(-5, 5), 0);
}

TEST(GccTesterBasic, IsEvenWorks) {
    GccTester t;
    EXPECT_TRUE(t.is_even(2));
    // Allow forcing a failing test via either compile-time macro or a
    // marker file created by the integration test harness.
    #ifdef FAIL_TEST
    EXPECT_TRUE(false);
    #else
    // marker path in /tmp used by integration scenario
    const char *marker = "/tmp/gcc_tester_fail_marker";
    std::ifstream fh(marker);
    if (fh.good()) {
        EXPECT_TRUE(t.is_even(3));
    } else {
        EXPECT_FALSE(t.is_even(3));
    }
    #endif
}
