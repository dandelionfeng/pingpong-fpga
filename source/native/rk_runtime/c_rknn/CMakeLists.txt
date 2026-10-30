set(c_source "${PIPELINE_PACKAGE_SOURCE}/software/pc_pipeline/modules/c_actual")
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(NOT EXISTS "${RKNN_INCLUDE_DIR}/rknn_api.h" OR NOT EXISTS "${RKNN_RUNTIME_LIBRARY}")
  message(FATAL_ERROR "Matching private RKNN header and board runtime are required")
endif()
set(generated "${CMAKE_CURRENT_BINARY_DIR}/generated")
execute_process(COMMAND "${Python3_EXECUTABLE}"
  "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/board_runtime/prepare_c_rknn.py"
  --source "${c_source}" --output "${generated}"
  RESULT_VARIABLE prepare_result)
if(NOT prepare_result EQUAL 0)
  message(FATAL_ERROR "Cannot prepare the verified C sources")
endif()
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/../../optimized/detector_backend_c_actual.cpp" "${generated}/detector_backend_c_actual.cpp" COPYONLY)
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/../../optimized/internal_onnx.hpp" "${generated}/internal_onnx.hpp" COPYONLY)
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/../../optimized/specialist_detector.hpp" "${generated}/specialist_detector.hpp" COPYONLY)
add_library(pipeline_c_module STATIC
  "${generated}/perception_engine.cpp" "${generated}/balltrack_onnx.cpp"
  "${generated}/preprocessing.cpp" "${generated}/postprocessing.cpp"
  "${generated}/yolo_detector.cpp" "${generated}/detector_backend_c_actual.cpp"
  runtime_session.cpp)
target_include_directories(pipeline_c_module PRIVATE
  "${generated}" "${CMAKE_CURRENT_SOURCE_DIR}" "${c_source}/include" "${RKNN_INCLUDE_DIR}")
target_link_libraries(pipeline_c_module PUBLIC pipeline_module_api "${RKNN_RUNTIME_LIBRARY}")
target_compile_options(pipeline_c_module PRIVATE -Wall -Wextra -Wpedantic)
