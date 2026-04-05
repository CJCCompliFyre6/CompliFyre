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
    fetch("/recent-tasks")
      .then((response) => response.json())
      .then((tasks) => {
        const notificationList = document.getElementById("notification-list");
        const noNotifications = document.getElementById(
          "no-notifications-message"
        );

        if (tasks.length > 0) {
          noNotifications.classList.add("hidden");
          notificationList.innerHTML = "";

          tasks.forEach((task) => {
            this.addOrUpdateTaskNotification(task);
          });
        } else {
          noNotifications.classList.remove("hidden");
        }
      });
  }

  addOrUpdateTaskNotification(taskData) {
    let notificationEl = document.getElementById(`task-${taskData.task_id}`);

    if (!notificationEl) {
      const template = document.getElementById(
        "progress-notification-template"
      );
      notificationEl = template.cloneNode(true);
      notificationEl.id = `task-${taskData.task_id}`;
      notificationEl.classList.remove("hidden");

      document.getElementById("notification-list").prepend(notificationEl);
    }

    // Update notification content
    notificationEl.querySelector(".task-name").textContent =
      this.formatTaskName(taskData.task_name);
    notificationEl.querySelector(
      ".task-progress"
    ).textContent = `${taskData.progress}%`;
    notificationEl.querySelector(
      ".task-progress-bar"
    ).style.width = `${taskData.progress}%`;
    notificationEl.querySelector(".task-message").textContent =
      taskData.message;
    notificationEl.querySelector(".task-time").textContent = this.formatTime(
      taskData.timestamp
    );

    // Update colors based on status
    const progressBar = notificationEl.querySelector(".task-progress-bar");
    if (taskData.status === "completed") {
      progressBar.classList.remove("bg-blue-600");
      progressBar.classList.add("bg-green-600");
    } else if (taskData.status === "failed") {
      progressBar.classList.remove("bg-blue-600");
      progressBar.classList.add("bg-red-600");
    }

    this.activeTasks.set(taskData.task_id, taskData);
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
    const now = new Date();
    const taskTime = new Date(timestamp);
    const diffMs = now - taskTime;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins} min ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hr ago`;

    return taskTime.toLocaleDateString();
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
      const taskData = JSON.parse(event.data);
      this.addOrUpdateTaskNotification(taskData);

      // Close connection if task is completed or failed
      if (taskData.status === "completed" || taskData.status === "failed") {
        console.log("Task completed or failed, closing connection");
        this.eventSource.close();
      }
    };

    this.eventSource.onerror = (error) => {
      console.error("EventSource failed:", error);
      this.eventSource.close();
    };
  }
}

// Initialize when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM loaded, initializing TaskNotifier");
  window.taskNotifier = new TaskNotifier();
});
