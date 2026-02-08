if(DEFINED FAIL_TEST AND FAIL_TEST)
	add_compile_definitions(FAIL_TEST)
endif()

add_executable(test_gcc_tester test_gcc_tester.cpp)

# Link order: project library first, then gtest main
if(TARGET GTest::gtest_main)
	target_link_libraries(test_gcc_tester PRIVATE gcc_tester_lib GTest::gtest_main)
else()
	target_link_libraries(test_gcc_tester PRIVATE gcc_tester_lib gtest_main)
endif()

include(GoogleTest)
gtest_discover_tests(test_gcc_tester)
