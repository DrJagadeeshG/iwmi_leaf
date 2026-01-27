# Why Not Streamlit? Architecture Decision

## Background

The LEAF DSS (Landscape Evaluation & Assessment Framework) was initially developed using Streamlit. While Streamlit enabled rapid prototyping, several limitations emerged as the application matured.

## Streamlit Limitations

### 1. Performance Issues
- **Full Page Reruns**: Streamlit reruns the entire script on every user interaction, causing performance bottlenecks with large geospatial datasets
- **State Management**: Complex state handling required workarounds using `st.session_state`, leading to convoluted code
- **Map Rendering**: Each interaction caused map re-rendering, resulting in poor user experience

### 2. Customization Constraints
- **Limited Styling**: CSS customization is restricted and requires hacky workarounds
- **Component Limitations**: Built-in components lack flexibility for complex UI requirements
- **Branding**: Difficult to implement consistent IWMI branding across the application

### 3. Scalability Concerns
- **Single-threaded**: Streamlit runs in a single thread, limiting concurrent user handling
- **Resource Usage**: High memory consumption due to script reruns
- **Caching Complexity**: `@st.cache` has quirks with mutable objects like GeoDataFrames

### 4. Deployment Challenges
- **Streamlit Cloud Limitations**: Free tier has resource constraints
- **Custom Deployment**: Requires specific server configuration
- **No Static Asset Control**: Limited control over CDN and caching strategies

## New Architecture Benefits

### Flask + HTML/CSS/JS Approach

| Aspect | Streamlit | Flask + JS |
|--------|-----------|------------|
| Page Load | Full rerun on interaction | Single page app, API calls |
| Map Updates | Complete re-render | Incremental layer updates |
| Styling | Limited CSS | Full CSS control |
| State | Session state workarounds | Client-side state management |
| API | Implicit | Explicit REST endpoints |
| Caching | Script-level | HTTP caching + server caching |
| Scalability | Single thread | Multi-worker with Gunicorn |

### Key Improvements

1. **Separation of Concerns**
   - Backend: Flask handles data processing and API endpoints
   - Frontend: JavaScript manages UI interactions and map rendering
   - Styling: CSS provides complete design control

2. **Performance**
   - API-driven architecture enables efficient data fetching
   - Map interactions don't trigger backend calls
   - Client-side filtering reduces server load

3. **User Experience**
   - Instant map interactions (pan, zoom, click)
   - Smooth transitions and animations
   - Responsive design with proper breakpoints

4. **Maintainability**
   - Clear code organization
   - Testable API endpoints
   - Standard web development practices

## Conclusion

While Streamlit excels at rapid prototyping and simple dashboards, the LEAF DSS requirements demanded a more robust architecture. The Flask + JavaScript approach provides the performance, customization, and scalability needed for a production-grade geospatial decision support system.
