/*
* ==============================================================================
*  Copyright (c) 2026, Qualcomm Innovation Center, Inc. All rights reserved.
*
*  SPDX-License-Identifier: BSD-3-Clause
*
* ==============================================================================
* */

// =============================================================================
// Global State Variables
// =============================================================================

/** Whether inspection is currently active */
let patrolActive = false;

/** Timer for notification auto-hide */
let notificationTimer = null;

/** Polling interval in milliseconds */
const timerTimeout = 1 * 1000; // 1 second

/** Timer for status polling */
let statusTimer = null;

/** Timer for results polling */
let resultTimer = null;

/** Base URL for API requests */
const requestBaseUrl = "http://192.168.112.89:3333";

/** Cache map for rendered DOM nodes (Key: url, Value: DOM Element) */
const renderedNodesMap = new Map();

/** Detection Interval loading */
let detIntervalLoading = false;

/** startPatrol or endPatrol loading */
let patrolLoading = false;

// =============================================================================
// Pagination Variables
// =============================================================================

/** Number of items to display per page */
let itemsPerPage = 20;

/** Current page number (1-indexed) */
let currentPage = 1;

/** Array containing all detection results */
let allResults = [];

// =============================================================================
// HTTP Request Wrapper
// =============================================================================

/**
 * Generic fetch wrapper with error handling and automatic JSON/text parsing
 *
 * @param {string} url - The URL to request
 * @param {Object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<any>} Parsed response data
 * @throws {Error} If request fails or returns non-OK status
 */
async function request(url, options = {}) {
  try {
    // Make the HTTP request
    const res = await fetch(url, {
      ...options,
    });

    // Determine response content type
    const contentType = res.headers.get("content-type") || "";

    // Parse response based on content type
    let data;
    if (contentType.includes("application/json")) {
      data = await res.json();
    } else {
      data = await res.text();
    }

    // Handle non-OK responses
    if (!res.ok) {
      // Extract error message from response
      const message =
        (data && data.message) ||
        (typeof data === "string" &&
          data.replace(/<[^>]*>/g, "").slice(0, 200)) ||
        `Request failed: ${res.status} ${res.statusText}`;

      throw new Error(message);
    }

    return data;
  } catch (error) {
    // Show error notification to user
    showNotification(error.message || String(error), "error");
    throw error;
  }
}

// =============================================================================
// Notification System
// =============================================================================

/**
 * Display a toast notification to the user
 *
 * @param {string} message - Message to display
 * @param {string} type - Notification type: "success" or "error"
 */
function showNotification(message, type = "success") {
  // Clear existing notification timer
  if (notificationTimer) {
    clearTimeout(notificationTimer);
    notificationTimer = null;
  }

  const notification = document.getElementById("notification");
  const notificationText = document.getElementById("notificationText");

  // Set message and show notification with appropriate styling
  notificationText.textContent = message;
  notification.className = `notification ${type} show`;

  // Auto-hide after 3 seconds
  notificationTimer = setTimeout(() => {
    notification.classList.remove("show");
  }, 3000);
}

// =============================================================================
// Status Management
// =============================================================================

/**
 * Poll the server for current inspection status and update UI
 * Automatically schedules next poll after completion
 *
 * @param {Function} cb - Optional callback to execute after status update
 */
function updateStatus(cb) {
  // Clear existing status timer
  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }

  request("/get_status")
    .then((data) => {
      // Get DOM elements
      const statusValue = document.getElementById("statusValue");
      const startBtn = document.getElementById("btn-start");
      const endBtn = document.getElementById("btn-end");
      const intervalInput = document.getElementById("intervalInput");

      // Update detection interval placeholder
      if (data.det_step !== undefined) {
        intervalInput.placeholder = data.det_step;
      }

      // Toggle button visibility and status styling based on inspection state
      if (data.patrol_status === "Active") {
        statusValue.textContent = "ACTIVE";
        statusValue.classList.add("active");
        startBtn.classList.remove("btn-show");
        endBtn.classList.add("btn-show");
      } else {
        statusValue.textContent = "IDLE";
        statusValue.classList.remove("active");
        startBtn.classList.add("btn-show");
        endBtn.classList.remove("btn-show");
      }
    })
    .catch((error) => console.error("Error:", error))
    .finally(() => {
      // Schedule next status poll
      statusTimer = setTimeout(updateStatus, timerTimeout);
      // Execute callback if provided
      cb && cb();
    });
}

// =============================================================================
// Detection Interval Configuration
// =============================================================================

/**
 * Set the detection interval (time between consecutive detections)
 * Validates input and sends configuration to server
 */
function setDetInterval() {
  if (detIntervalLoading) return;
  const intervalInput = document.getElementById("intervalInput");
  const step = parseFloat(intervalInput.value);

  // Validate input
  if (isNaN(step) || step <= 0) {
    showNotification("Please enter a valid detection interval", "error");
    return;
  }
  if (step < 0.1) {
    showNotification("Minimum detection interval is 0.1 seconds", "error");
    return;
  }

  detIntervalLoading = true;
  // Send configuration to server
  request("/set_det_step", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ step: step.toString() }),
  })
    .then((data) => {
      console.log(data);
      if (data.status === "success") {
        showNotification(`Detection interval set to ${step} seconds`, "success");
        // Refresh status and clear input
        updateStatus(() => {
          intervalInput.value = undefined;
        });
      } else {
        showNotification(data.message || `Configuration failed, please try again`, "error");
      }
    })
    .catch((error) => {
      console.error("Error:", error);
    })
    .finally(() => {
      detIntervalLoading = false;
    });
}

// =============================================================================
// Inspection Control
// =============================================================================

/**
 * Start the inspection process
 * Sends start command to server and updates UI state
 */
function startPatrol() {
  if (patrolLoading) return;
  patrolLoading = true;
  request("/start_patrol", { method: "POST" })
    .then((data) => {
      patrolActive = true;
      updateStatus();
    })
    .catch((error) => {
      console.error("Error:", error);
    })
    .finally(() => {
      patrolLoading = false;
    });
}

/**
 * End the inspection process
 * Sends stop command to server and updates UI state
 */
function endPatrol() {
  if (patrolLoading) return;
  patrolLoading = true;
  request("/end_patrol", { method: "POST" })
    .then((data) => {
      patrolActive = false;
      updateStatus();
    })
    .catch((error) => {
      console.error("Error:", error);
    })
    .finally(() => {
      patrolLoading = false;
    });
}

// =============================================================================
// Results Management
// =============================================================================

/**
 * Poll the server for detection results and update display
 * Automatically schedules next poll after completion
 */
function updateResults() {
  // Clear existing results timer
  if (resultTimer) {
    clearTimeout(resultTimer);
    resultTimer = null;
  }

  request("/get_result")
    .then((data) => {
      // Reverse array to show newest results first
      allResults = data.reverse() || [];
      renderResults();
    })
    .catch((error) => {
      console.error("updateResults Error:", error, error.message);
      showNotification(error.message || error, "error");
    })
    .finally(() => {
      // Schedule next results poll
      resultTimer = setTimeout(updateResults, timerTimeout);
    });
}

// =============================================================================
// Results Rendering with Pagination
// =============================================================================

/**
 * Render detection results with pagination support
 * Handles empty state, pagination controls, and result cards
 */
function renderResults() {
  // Get DOM elements
  const resultsGrid = document.getElementById("resultsGrid");
  const resultCount = document.getElementById("resultCount");
  const pageInfo = document.getElementById("pageInfo");
  const prevBtn = document.getElementById("prevPage");
  const nextBtn = document.getElementById("nextPage");
  const pagination = document.getElementById("pagination");

  // Update result count badge
  resultCount.textContent =
    allResults.length > 0 ? `(${allResults.length})` : "";

  // Display empty state if no results
  if (allResults.length === 0) {
    resultsGrid.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📋</div>
        <div class="empty-state-text">No detection results yet</div>
      </div>`;
    pagination.style.display = "none";
    return;
  }

  // Calculate pagination
  const totalPages = Math.ceil(allResults.length / itemsPerPage);

  // Ensure current page is within valid range
  if (currentPage > totalPages) {
    currentPage = totalPages;
  }
  if (currentPage < 1) {
    currentPage = 1;
  }

  // Get results for current page
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const pageResults = allResults.slice(startIndex, endIndex);

  // Clear grid and render current page
  resultsGrid.innerHTML = "";

  pageResults.forEach((result) => {
    // Create result card
    const card = document.createElement("div");
    card.className = "defect-card";
    card.onclick = () => viewDefect(result.path, result.time);

    card.innerHTML = `
      <img
        src="${result.path}"
        alt="Detected Defect"
        class="defect-card-image"
        loading="lazy"
        decoding="async"
      >
      <div class="defect-card-title">Time: ${result.time}</div>
    `;

    resultsGrid.appendChild(card);
  });

  // Update pagination controls
  pageInfo.textContent = `Page ${currentPage} / ${totalPages}`;
  prevBtn.disabled = currentPage === 1;
  nextBtn.disabled = currentPage === totalPages;
  pagination.style.display = allResults.length > 0 ? "flex" : "none";
}

// =============================================================================
// Pagination Controls
// =============================================================================

/**
 * Navigate to next or previous page
 *
 * @param {number} direction - Direction to navigate (-1 for previous, +1 for next)
 */
function changePage(direction) {
  const totalPages = Math.ceil(allResults.length / itemsPerPage);
  const newPage = currentPage + direction;

  // Only change page if within valid range
  if (newPage >= 1 && newPage <= totalPages) {
    currentPage = newPage;
    renderResults();
  }
}

/**
 * Handle items per page change
 * Resets to page 1 after changing page size
 */
function changePageSize() {
  const select = document.getElementById("pageSizeSelect");
  itemsPerPage = parseInt(select.value);
  currentPage = 1; // Reset to first page when changing page size
  renderResults();
}

/**
 * Handle jump to page input (Enter key or blur)
 *
 * @param {KeyboardEvent} e - Keyboard event
 */
function handleJumpKeydown(e) {
  if (e.key === "Enter") {
    const input = document.getElementById("jumpPageInput");
    let targetPage = parseInt(input.value);
    const totalPages = Math.ceil(allResults.length / itemsPerPage);

    // Validate input
    if (isNaN(targetPage)) {
      input.value = "";
      return;
    }

    // Clamp to valid range
    targetPage = Math.max(1, targetPage);
    targetPage = Math.min(targetPage, totalPages);

    // Jump to page
    currentPage = targetPage;
    renderResults();
    input.value = ""; // Clear input after jump
    input.blur(); // Remove focus
  }
}

// =============================================================================
// Image Viewer
// =============================================================================

/** Current zoom level (1 = 100%) */
let currentZoom = 1;

/** Minimum allowed zoom level */
const MIN_ZOOM = 0.1;

/** Maximum allowed zoom level */
const MAX_ZOOM = 10;

/** Flag to prevent multiple scrollbar fix attempts */
let pendingScrollbarFix = false;

/**
 * Open image viewer modal with specified image
 *
 * @param {string} filepath - Path to the image file
 * @param {string} time - Detection timestamp
 */
function viewDefect(filepath, time) {
  const viewer = document.getElementById("imageViewer");
  const viewerImage = document.getElementById("viewerImage");
  const viewerInfo = document.getElementById("viewerInfo");

  // Set image source and metadata
  viewerImage.src = filepath;
  viewerInfo.textContent = `Detection Time: ${time}`;
  viewer.classList.add("show");

  // Reset zoom to 100%
  currentZoom = 1;
  updateImageZoom();

  // Prevent body scroll when viewer is open
  document.body.style.overflow = "hidden";
}

/**
 * Close the image viewer modal
 */
function closeImageViewer() {
  const viewer = document.getElementById("imageViewer");
  viewer.classList.remove("show");
  document.body.style.overflow = "";

  // Reset zoom
  currentZoom = 1;
  updateImageZoom();
}

/**
 * Zoom the image by a delta amount
 *
 * @param {number} delta - Amount to zoom (positive to zoom in, negative to zoom out)
 */
function zoomImage(delta) {
  currentZoom += delta;
  // Clamp zoom level to valid range
  currentZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, currentZoom));
  updateImageZoom();
}

/**
 * Reset zoom to 100%
 */
function resetZoom() {
  currentZoom = 1;
  updateImageZoom();
}

/**
 * Update the image zoom transform and zoom button text
 * Includes multi-layer scrollbar fix for cross-browser compatibility
 */
function updateImageZoom() {
  const viewerImage = document.getElementById("viewerImage");
  const imageWrapper = document.getElementById("imageWrapper");
  const zoomResetBtn = document.querySelector(".zoom-reset");

  // Apply zoom transformation
  viewerImage.style.transform = `scale(${currentZoom})`;

  // Update reset button text to show current zoom percentage
  if (zoomResetBtn) {
    zoomResetBtn.textContent = `${Math.round(currentZoom * 100)}%`;
  }

  // Multi-layer scrollbar fix for browser reflow issues
  // Layer 1: Synchronous forced reflow
  imageWrapper.style.overflow = 'hidden';
  void imageWrapper.offsetHeight; // Force immediate reflow
  imageWrapper.style.overflow = 'auto';

  // Layer 2: Promise microtask (executes after current macrotask)
  if (!pendingScrollbarFix) {
    pendingScrollbarFix = true;
    Promise.resolve().then(() => {
      imageWrapper.style.overflow = 'hidden';
      void imageWrapper.offsetHeight;
      imageWrapper.style.overflow = 'auto';

      // Layer 3: setTimeout macrotask (executes in next event loop)
      setTimeout(() => {
        imageWrapper.style.overflow = 'hidden';
        void imageWrapper.offsetHeight;
        imageWrapper.style.overflow = 'auto';
        pendingScrollbarFix = false;
      }, 0);
    });
  }
}

// =============================================================================
// Keyboard Event Handlers
// =============================================================================

/**
 * Global keyboard shortcuts
 * - ESC: Close image viewer
 * - +/=: Zoom in (when viewer is open)
 * - -/_: Zoom out (when viewer is open)
 * - 0: Reset zoom (when viewer is open)
 */
document.addEventListener("keydown", (e) => {
  // ESC to close viewer
  if (e.key === "Escape") {
    closeImageViewer();
  }

  // Zoom shortcuts (only when viewer is open)
  if (document.getElementById("imageViewer").classList.contains("show")) {
    if (e.key === "+" || e.key === "=") {
      zoomImage(0.2);
    } else if (e.key === "-" || e.key === "_") {
      zoomImage(-0.2);
    } else if (e.key === "0") {
      resetZoom();
    }
  }
});

// =============================================================================
// Page Initialization
// =============================================================================

/**
 * Initialize the application when page loads
 * - Start status polling
 * - Start results polling
 */
window.onload = () => {
  updateStatus();
  updateResults();
};
