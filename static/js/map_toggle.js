document.addEventListener("DOMContentLoaded", function () {
  const toggleBtn = document.getElementById("locationToggleBtn");
  if (!toggleBtn) return;

  const imageId = toggleBtn.getAttribute("data-image-id");
  const wrapper = document.getElementById(`mapToggleWrapper-${imageId}`);
  if (!wrapper) return;

  const lat = parseFloat(wrapper.getAttribute("data-lat"));
  const lng = parseFloat(wrapper.getAttribute("data-lng"));
  const address = wrapper.getAttribute("data-address");
  const viewport = document.getElementById(`mapViewport-${imageId}`);
  const spinner = document.getElementById(`mapSpinner-${imageId}`);

  let mapLoaded = false;

  toggleBtn.addEventListener("click", function () {
    const isFlipped = wrapper.classList.toggle("flipped");
    
    if (isFlipped) {
      toggleBtn.classList.add("active");
      toggleBtn.innerHTML = `🖼️ Ver imagem`;
      
      // Lazy load the Leaflet map on first toggle
      if (!mapLoaded) {
        loadMap();
      }
    } else {
      toggleBtn.classList.remove("active");
      toggleBtn.innerHTML = `📍 Mostrar mapa`;
    }
  });

  function loadMap() {
    mapLoaded = true;

    // Check if coordinates exist. If not, map cannot be rendered normally
    if (isNaN(lat) || isNaN(lng) || lat === 0 && lng === 0) {
      console.warn("Coordenadas em falta. Fallback para pesquisa por endereço no OpenStreetMap.");
      renderFallback();
      return;
    }

    renderLeafletMap();
  }

  function renderLeafletMap() {
    loadLeafletAssets(function () {
      try {
        viewport.innerHTML = "";
        
        // Initialize Leaflet Map
        const map = L.map(viewport).setView([lat, lng], 15);
        
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(map);

        // Add Location Pin (Marker)
        const marker = L.marker([lat, lng]).addTo(map);
        if (address) {
          marker.bindPopup(`<b>Localização</b><br>${address}`).openPopup();
        }

        // Adjust sizes after rendering in active element to prevent grey tiles
        setTimeout(function () {
          map.invalidateSize();
          if (spinner) spinner.classList.add("hidden");
        }, 150);

      } catch (err) {
        console.error("Erro ao instanciar o mapa Leaflet:", err);
        renderFallback();
      }
    });
  }

  // Fallback if no coordinates or Leaflet fails
  function renderFallback() {
    viewport.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; padding:2rem; text-align:center;">
        <span style="font-size:2rem; margin-bottom:0.5rem;">📍</span>
        <h4 style="margin:0 0 0.5rem 0;">Localização registada</h4>
        <p style="margin:0 0 1rem 0; font-size:0.9rem; color:var(--muted);">${address || "Sem endereço disponível."}</p>
        <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address || '')}" 
           target="_blank" 
           class="btn-open-gmaps">
           Procurar no Google Maps
        </a>
      </div>
    `;
    if (spinner) spinner.classList.add("hidden");
  }

  // Helper to load Leaflet JS and CSS dynamically on the fly
  function loadLeafletAssets(callback) {
    if (window.L) {
      callback();
      return;
    }

    // Load Leaflet CSS
    if (!document.getElementById("leaflet-css")) {
      const link = document.createElement("link");
      link.id = "leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }

    // Load Leaflet JS
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = callback;
    script.onerror = function () {
      console.error("Falha ao descarregar biblioteca Leaflet.");
      renderFallback();
    };
    document.head.appendChild(script);
  }
});
