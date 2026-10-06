cmake_minimum_required(VERSION 3.20)
project(ball_measurement LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs)
add_library(ball_measurement src/ball_measurement.cpp)
target_include_directories(ball_measurement PUBLIC include ${OpenCV_INCLUDE_DIRS})
target_link_libraries(ball_measurement PUBLIC ${OpenCV_LIBS})
if(MSVC)
    target_compile_options(ball_measurement PUBLIC /EHsc /utf-8)
endif()
add_executable(test_ball_measurement tests/test_ball_measurement.cpp)
target_link_libraries(test_ball_measurement PRIVATE ball_measurement ${OpenCV_LIBS})
add_executable(ball_measurement_cli apps/ball_measurement_cli.cpp)
target_link_libraries(ball_measurement_cli PRIVATE ball_measurement)
if(WIN32 AND TARGET opencv_world)
    # Keep the matching runtime beside the generated executable, so CTest and
    # direct execution don't depend on a global PATH or another OpenCV version.
    add_custom_command(TARGET test_ball_measurement POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:opencv_world> $<TARGET_FILE_DIR:test_ball_measurement>)
    add_custom_command(TARGET ball_measurement_cli POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:opencv_world> $<TARGET_FILE_DIR:ball_measurement_cli>)
endif()
include(CTest)
if(BUILD_TESTING)
    add_test(NAME ball_region_selection COMMAND test_ball_measurement selection)
    add_test(NAME frame_identity_and_roi COMMAND test_ball_measurement identity)
    add_test(NAME quality_and_prediction COMMAND test_ball_measurement quality)
endif()
