// Toggle Sidebar
function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
  const menuIcon = document.querySelector(".menu-icon i"); // Get the current icon

  // Toggle the icon when the sidebar opens or closes
  if (menuIcon.classList.contains("bx-menu")) {
    menuIcon.classList.replace("bx-menu", "bx-x"); // Switch to close icon
  } else {
    menuIcon.classList.replace("bx-x", "bx-menu"); // Switch back to menu icon
  }
}

// Function to close the sidebar when clicking outside
function closeSidebarIfClickedOutside(event) {
  const sidebar = document.getElementById("sidebar");
  const menuIcon = document.querySelector(".menu-icon i");

  // Check if the click is outside the sidebar and not on the menu icon
  if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
    sidebar.classList.remove("open");
    menuIcon.classList.replace("bx-x", "bx-menu"); // Revert the icon back to the menu
  }
}

// Add the event listener to close sidebar if clicking outside
document.addEventListener("click", closeSidebarIfClickedOutside);

function toggleSubmenu(event) {
  event.preventDefault(); // Prevents page reload

  let parent = event.target.closest(".submenu"); // Find the clicked <li>
  let submenu = parent.querySelector(".submenu-items"); // Find submenu in this <li>

  // Close all other submenus before opening the clicked one
  document.querySelectorAll(".submenu-items").forEach((item) => {
    if (item !== submenu) {
      item.classList.remove("open"); // Use class to control the display
      item.style.display = "none"; // Remove inline style if necessary
      item.parentElement.classList.remove("open");
    }
  });

  // Toggle the clicked submenu
  if (submenu.classList.contains("open")) {
    submenu.classList.remove("open");
    submenu.style.display = "none"; // Close
    parent.classList.remove("open");
  } else {
    submenu.classList.add("open");
    submenu.style.display = "block"; // Open
    parent.classList.add("open");
  }
}

document
  .getElementById("guidelineForm")
  .addEventListener("submit", function (event) {
    event.preventDefault();

    let guidelineName = document.getElementById("guidelineName").value;
    let gid = document.getElementById("gid").value;
    let issuingAuthority = document.getElementById("issuingAuthority").value;
    let applicableGeography = document.getElementById(
      "applicableGeography"
    ).value;
    let applicableIndustry =
      document.getElementById("applicableIndustry").value;
    let applicableCategory =
      document.getElementById("applicableCategory").value;
    let dateOfIssue = document.getElementById("dateOfIssue").value;
    let complianceDate = document.getElementById("complianceDate").value;
    let mandatory = document.querySelector(
      'input[name="mandatory"]:checked'
    )?.value;
    let certification = document.querySelector(
      'input[name="certification"]:checked'
    )?.value;

    if (
      !guidelineName ||
      !gid ||
      !issuingAuthority ||
      !applicableGeography ||
      !dateOfIssue ||
      !complianceDate ||
      !mandatory ||
      !certification
    ) {
      alert("Please fill in all required fields.");
      return;
    }

    let formData = {
      guidelineName,
      gid,
      issuingAuthority,
      applicableGeography,
      applicableIndustry,
      applicableCategory,
      dateOfIssue,
      complianceDate,
      mandatory,
      certification,
    };

    console.log("Form Submitted:", formData);
    alert("Guideline added successfully!");
  });

function uploadFile() {
  let fileInput = document.getElementById("fileInput");
  let file = fileInput.files[0]; // Get the first selected file

  if (file) {
    document.getElementById("fileName").innerText =
      "Selected file: " + file.name;
  } else {
    alert("Please select a file first!");
  }
}
