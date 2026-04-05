// static/js/notifications.js
class TaskNotifier {
  constructor() {
    console.log("TaskNotifier initialized");
    this.eventSource = null;
    this.activeTasks = new Map();
    this.setupEventListeners();
    this.loadRecentTasks();
  }

  setupEventListeners() {
    // Listen for notification toggle
    const notificationToggle = document.getElementById("notification-toggle");
    if (notificationToggle) {
      notificationToggle.addEventListener("click", () => {
        console.log("Notification bell clicked");
        this.loadRecentTasks();
      });
    } else {
      console.error("Notification toggle element not found");
    }
  }

  loadRecentTasks() {
    fetch("/api/notifications/recent-tasks")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then((tasks) => {
        const notificationList = document.getElementById("notification-list");
        const noNotifications = document.getElementById(
          "no-notifications-message"
        );

        if (!notificationList || !noNotifications) {
          console.error("Notification elements not found");
          return;
        }

        if (tasks && tasks.length > 0) {
          noNotifications.classList.add("hidden");
          notificationList.innerHTML = "";

          tasks.forEach((task) => {
            this.addOrUpdateTaskNotification(task);
          });
        } else {
          noNotifications.classList.remove("hidden");
          notificationList.innerHTML = "";
        }
      })
      .catch((error) => {
        console.error("Error loading recent tasks:", error);
      });
  }

  addOrUpdateTaskNotification(taskData) {
    // Check if template exists
    const template = document.getElementById("progress-notification-template");
    if (!template) {
      console.error("Progress notification template not found");
      this.createFallbackNotification(taskData);
      return;
    }

    let notificationEl = document.getElementById(`task-${taskData.task_id}`);
    const notificationList = document.getElementById("notification-list");

    if (!notificationList) {
      console.error("Notification list element not found");
      return;
    }

    if (!notificationEl) {
      // Clone the template
      notificationEl = template
        .querySelector(".notification-item")
        .cloneNode(true);
      notificationEl.id = `task-${taskData.task_id}`;
      notificationList.prepend(notificationEl);
    }

    // Update notification content
    this.updateNotificationContent(notificationEl, taskData);
    this.activeTasks.set(taskData.task_id, taskData);
  }

  updateNotificationContent(notificationEl, taskData) {
    const elements = {
      taskName: notificationEl.querySelector(".task-name"),
      taskProgress: notificationEl.querySelector(".task-progress"),
      taskProgressBar: notificationEl.querySelector(".task-progress-bar"),
      taskMessage: notificationEl.querySelector(".task-message"),
      taskTime: notificationEl.querySelector(".task-time"),
    };

    // Update each element if it exists
    if (elements.taskName)
      elements.taskName.textContent = this.formatTaskName(taskData.task_name);
    if (elements.taskProgress)
      elements.taskProgress.textContent = `${taskData.progress}%`;
    if (elements.taskProgressBar)
      elements.taskProgressBar.style.width = `${taskData.progress}%`;
    if (elements.taskMessage)
      elements.taskMessage.textContent = taskData.message;
    if (elements.taskTime)
      elements.taskTime.textContent = this.formatTime(taskData.timestamp);

    // Update colors based on status
    if (elements.taskProgressBar) {
      elements.taskProgressBar.classList.remove(
        "bg-blue-600",
        "bg-green-600",
        "bg-red-600"
      );

      if (taskData.status === "completed") {
        elements.taskProgressBar.classList.add("bg-green-600");
      } else if (taskData.status === "failed") {
        elements.taskProgressBar.classList.add("bg-red-600");
      } else {
        elements.taskProgressBar.classList.add("bg-blue-600");
      }
    }
  }

  createFallbackNotification(taskData) {
    const notificationList = document.getElementById("notification-list");
    const noNotifications = document.getElementById("no-notifications-message");

    if (!notificationList || !noNotifications) return;

    noNotifications.classList.add("hidden");

    const notificationEl = document.createElement("div");
    notificationEl.id = `task-${taskData.task_id}`;
    notificationEl.className = "border-b border-gray-100";
    notificationEl.innerHTML = `
      <div class="px-4 py-2">
        <div class="flex justify-between items-center mb-1">
          <span class="text-sm font-medium text-gray-900">${this.formatTaskName(
            taskData.task_name
          )}</span>
          <span class="text-xs text-gray-500">${taskData.progress}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-1.5 mb-1">
          <div class="h-1.5 rounded-full ${
            taskData.status === "completed"
              ? "bg-green-600"
              : taskData.status === "failed"
              ? "bg-red-600"
              : "bg-blue-600"
          }" 
               style="width: ${taskData.progress}%"></div>
        </div>
        <div class="text-xs text-gray-500">${taskData.message}</div>
        <div class="text-xs text-gray-400">${this.formatTime(
          taskData.timestamp
        )}</div>
      </div>
    `;

    notificationList.prepend(notificationEl);
  }

  formatTaskName(taskName) {
    const nameMap = {
      extract_guidelines: "Extract Guidelines",
      extract_clauses: "Extract Clauses",
      extract_activities: "Extract Activities",
      extract_test_procedures: "Extract Test Procedures",
      extract_all_activities_and_tests: "Extract All Activities & Tests",
    };
    return nameMap[taskName] || taskName;
  }

  formatTime(timestamp) {
    try {
      const now = new Date();
      const taskTime = new Date(timestamp);
      const diffMs = now - taskTime;
      const diffMins = Math.floor(diffMs / 60000);

      if (diffMins < 1) return "Just now";
      if (diffMins < 60) return `${diffMins} min ago`;

      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours} hr ago`;

      return taskTime.toLocaleDateString();
    } catch (e) {
      return "Recently";
    }
  }

  startMonitoringTask(taskId) {
    console.log("Starting to monitor task:", taskId);

    if (this.eventSource) {
      this.eventSource.close();
    }

    this.eventSource = new EventSource(
      `/api/notifications/task-status/${taskId}`
    );
    console.log("EventSource created for task:", taskId);

    this.eventSource.onmessage = (event) => {
      console.log("Received task update:", event.data);
      try {
        const taskData = JSON.parse(event.data);
        this.addOrUpdateTaskNotification(taskData);

        // Close connection if task is completed or failed
        if (taskData.status === "completed" || taskData.status === "failed") {
          console.log("Task completed or failed, closing connection");
          this.eventSource.close();
        }
      } catch (e) {
        console.error("Error parsing task data:", e);
      }
    };

    this.eventSource.onerror = (error) => {
      console.error("EventSource failed:", error);
      if (this.eventSource) {
        this.eventSource.close();
      }
    };
  }
}

// Initialize when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM loaded, initializing TaskNotifier");
  window.taskNotifier = new TaskNotifier();
});
