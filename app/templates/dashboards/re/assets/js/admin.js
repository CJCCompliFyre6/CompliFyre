// Toggle Sidebar
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    const menuIcon = document.querySelector(".menu-icon i");
  
    if (menuIcon.classList.contains("bx-menu")) {
        menuIcon.classList.replace("bx-menu", "bx-x");
    } else {
        menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }
  
  // Function to close the sidebar when clicking outside
  function closeSidebarIfClickedOutside(event) {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");
    
    if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
        sidebar.classList.remove("open");
        menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }
  
  // Add the event listener to close sidebar if clicking outside
  document.addEventListener("click", closeSidebarIfClickedOutside);
  
  function toggleSubmenu(event) {
    event.preventDefault();
  
    let parent = event.target.closest(".submenu");
    let submenu = parent.querySelector(".submenu-items");
  
    document.querySelectorAll(".submenu-items").forEach((item) => {
        if (item !== submenu) {
            item.classList.remove("open");
            item.style.display = "none";
            item.parentElement.classList.remove("open");
        }
    });
  
    if (submenu.classList.contains("open")) {
        submenu.classList.remove("open");
        submenu.style.display = "none";
        parent.classList.remove("open");
    } else {
        submenu.classList.add("open");
        submenu.style.display = "block";
        parent.classList.add("open");
    }
  }
  


function submitForm() {
    let userData = {
        fullName: document.getElementById("full-name").value,
        employeeId: document.getElementById("employee-id").value,
        email: document.getElementById("email").value,
        phone: document.getElementById("phone").value,
        dateJoining: document.getElementById("date-joining").value,
        gender: document.getElementById("gender").value,
        terminationDate: document.getElementById("termination-date").value,
        designation: document.getElementById("designation").value,
        jobLocation: document.getElementById("job-location").value,
        role: document.getElementById("role").value,
        reportingManager: document.getElementById("reporting-manager").value,
        employmentType: document.getElementById("employment-type").value
    };
    console.log("User Data Submitted:", userData);
    alert("User details submitted successfully!");
}