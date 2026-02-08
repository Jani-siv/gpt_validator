cmake_minimum_required(VERSION 3.14)
project(gcc_tester LANGUAGES CXX)

option(UNIT_TESTS "Build unit tests" OFF)

# Option to force a single test failure for integration testing
option(FAIL_TEST "Force one unit test to fail for integration testing" OFF)

# Option to force CI/integration failure for testing the test-runner
option(FAIL_BUILD "Force build to fail for integration testing" OFF)

if(FAIL_BUILD)
  message(FATAL_ERROR "FAIL_BUILD is ON: forcing CMake to fail for integration test")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(gcc_tester_lib src/gcc_tester.cpp)
target_include_directories(gcc_tester_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(UNIT_TESTS)
  # enable coverage-friendly flags for tests
  add_compile_options(--coverage -g)
  add_link_options(--coverage)

  enable_testing()
  if(FAIL_TEST)
    add_compile_definitions(FAIL_TEST=1)
  endif()
  # Try to use system-installed GTest first to avoid network fetches
  find_package(GTest QUIET)
  if(NOT GTest_FOUND)
    include(FetchContent)
    FetchContent_Declare(
      googletest
      URL https://github.com/google/googletest/archive/refs/tags/release-1.14.0.zip
      DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    FetchContent_MakeAvailable(googletest)
  endif()

  add_subdirectory(tests)
endif()


