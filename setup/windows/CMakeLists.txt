cmake_minimum_required(VERSION 3.14)
project(UmbraEdit LANGUAGES CXX)
add_executable(UmbraEdit main.cpp launcher.rc)
set_target_properties(UmbraEdit PROPERTIES WIN32_EXECUTABLE True)
