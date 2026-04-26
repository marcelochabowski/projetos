# Configuration
SRL_MAX_TEXTURES = 300          # Number of VDP1 texture slots
SRL_MODE = NTSC                 # Valid options are PAL or NTSC
SRL_HIGH_RES = 0                # 480i mode
SRL_FRAMERATE = 0               # Framerate control (0=dynamic, 1=< 60/value)
SRL_MAX_CD_BACKGROUND_JOBS = 1  # Maximum number of files GFS can open at once
SRL_MAX_CD_FILES = 256          # Maximum number of files on a CD
SRL_MAX_CD_RETRIES = 5          # Number of times to retry on unsuccessful read
SRL_MALLOC_METHOD = TLSF        # Allocation method: TLSF or SIMPLE are supported.

# Sound driver specific configuration
SRL_USE_SGL_SOUND_DRIVER = 0
SRL_ENABLE_FREQ_ANALYSIS = 0

# SGL configuration
SGL_MAX_VERTICES = 3000         # Number of vertices that can be used
SGL_MAX_POLYGONS = 2000         # Number of polygons that can be used
SGL_MAX_EVENTS = 1              # Number of events that can be used
SGL_MAX_WORKS = 1               # Number of works that can be used 

# Disk name
CD_NAME = BenchSaturnLimits

# Directory build will be placed into
BUILD_DROP = ./BuildDrop

# SRL installation directory
SRL_INSTALL_ROOT ?= ../..

# Find all .c and .cxx files
SOURCES = $(patsubst ./%,%,$(shell find src/ -name '*.c')) 
SOURCES += $(patsubst ./%,%,$(shell find src/ -name '*.cxx'))

# Include shared makefile
SDK_ROOT = $(SRL_INSTALL_ROOT)/saturnringlib
include $(SDK_ROOT)/shared.mk
