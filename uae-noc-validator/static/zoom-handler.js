/**
 * Image Zoom Handler for Document Preview
 * Provides click-to-zoom functionality for document thumbnails
 */

(function() {
    'use strict';
    
    // Wait for DOM to be fully loaded
    document.addEventListener('DOMContentLoaded', function() {
        initZoomHandler();
    });
    
    // Also initialize on Dash page updates
    if (window.dash_clientside) {
        window.dash_clientside = window.dash_clientside || {};
        window.dash_clientside.clientside = {
            initZoom: function() {
                initZoomHandler();
                return window.dash_clientside.no_update;
            }
        };
    }
    
    function initZoomHandler() {
        // Use event delegation to handle dynamically added images
        document.body.addEventListener('click', function(e) {
            const img = e.target;
            
            // Check if clicked element is a zoomable thumbnail
            if (img.classList && img.classList.contains('pdf-thumbnail-zoomable')) {
                e.preventDefault();
                e.stopPropagation();
                
                // Toggle zoom state
                if (img.classList.contains('pdf-thumbnail-zoomed')) {
                    zoomOut(img);
                } else {
                    zoomIn(img);
                }
            }
            
            // Check if clicked on overlay
            if (e.target.classList && e.target.classList.contains('zoom-overlay')) {
                e.preventDefault();
                const zoomedImg = document.querySelector('.pdf-thumbnail-zoomed');
                if (zoomedImg) {
                    zoomOut(zoomedImg);
                }
            }
        });
        
        // Handle Escape key to close zoom
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' || e.keyCode === 27) {
                const zoomedImg = document.querySelector('.pdf-thumbnail-zoomed');
                if (zoomedImg) {
                    e.preventDefault();
                    zoomOut(zoomedImg);
                }
            }
        });
    }
    
    function zoomIn(img) {
        // Create dark overlay
        const overlay = document.createElement('div');
        overlay.className = 'zoom-overlay';
        overlay.setAttribute('data-zoom-overlay', 'true');
        document.body.appendChild(overlay);
        
        // Store original parent and position for restoration
        img.setAttribute('data-original-parent', img.parentElement.className);
        
        // Add zoomed class
        img.classList.add('pdf-thumbnail-zoomed');
        img.classList.remove('pdf-thumbnail-zoomable');
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
    }
    
    function zoomOut(img) {
        // Remove zoomed class
        img.classList.remove('pdf-thumbnail-zoomed');
        img.classList.add('pdf-thumbnail-zoomable');
        
        // Remove overlay
        const overlay = document.querySelector('[data-zoom-overlay="true"]');
        if (overlay) {
            overlay.remove();
        }
        
        // Restore body scroll
        document.body.style.overflow = '';
        
        // Clean up data attributes
        img.removeAttribute('data-original-parent');
    }
})();
