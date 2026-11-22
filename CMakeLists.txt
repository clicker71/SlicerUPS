cmake_minimum_required(VERSION 3.16.3...3.29)

project(SlicerUPS)

set(EXTENSION_NAME SlicerUPS)
set(MODULE_NAME SlicerUPS)

find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

set(EXTENSION_HOMEPAGE "https://github.com/clicker71/SlicerUPS")
set(EXTENSION_CATEGORY "Informatics")
set(EXTENSION_CONTRIBUTORS "Daniil Solgalov (Clarus PACS)")
set(EXTENSION_DESCRIPTION
  "CLI-first DICOMweb UPS-RS (PS3.18) task requester and watcher.")
set(EXTENSION_STATUS "Alpha")
set(EXTENSION_DEPENDS "")

set(MODULE_NAME ${PROJECT_NAME})
set(MODULE_TITLE ${PROJECT_NAME})

set(MODULES_SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
set(MODULES_INSTALL_DIR ${CMAKE_CURRENT_SOURCE_DIR})

slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS SlicerUPS.py
  RESOURCES slicer_ups_client scripts hooks
  WITH_GENERIC_TESTS
)
