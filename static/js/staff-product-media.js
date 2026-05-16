document.addEventListener('DOMContentLoaded', () => {
  const input = document.querySelector('[data-media-input]');
  const previewSection = document.querySelector('[data-selected-media-section]');
  const previewGrid = document.querySelector('[data-media-preview-grid]');

  if (!input || !previewSection || !previewGrid) {
    return;
  }

  const revokeObjectUrls = () => {
    previewGrid.querySelectorAll('[data-object-url]').forEach((node) => {
      URL.revokeObjectURL(node.dataset.objectUrl);
    });
  };

  const buildCard = (file) => {
    const card = document.createElement('article');
    card.className = 'staff-media-card';

    const frame = document.createElement('div');
    frame.className = 'staff-media-card-frame';
    const type = file.type || '';

    if (type.startsWith('image/')) {
      const image = document.createElement('img');
      const objectUrl = URL.createObjectURL(file);
      image.src = objectUrl;
      image.alt = file.name;
      image.dataset.objectUrl = objectUrl;
      frame.appendChild(image);
    } else if (type.startsWith('video/')) {
      const video = document.createElement('video');
      const objectUrl = URL.createObjectURL(file);
      video.controls = true;
      video.preload = 'metadata';
      video.dataset.objectUrl = objectUrl;
      video.src = objectUrl;
      frame.appendChild(video);
    } else if (type.startsWith('audio/')) {
      const audioWrap = document.createElement('div');
      audioWrap.className = 'staff-media-audio';
      audioWrap.innerHTML = '<i class="bi bi-music-note-beamed" aria-hidden="true"></i>';

      const audio = document.createElement('audio');
      const objectUrl = URL.createObjectURL(file);
      audio.controls = true;
      audio.preload = 'none';
      audio.src = objectUrl;
      audio.dataset.objectUrl = objectUrl;
      audioWrap.appendChild(audio);
      frame.appendChild(audioWrap);
    }

    const meta = document.createElement('div');
    meta.className = 'staff-media-card-meta';

    const strong = document.createElement('strong');
    strong.textContent = file.name;

    const span = document.createElement('span');
    span.textContent = 'Ready to upload';

    meta.append(strong, span);
    card.append(frame, meta);
    return card;
  };

  input.addEventListener('change', () => {
    revokeObjectUrls();
    previewGrid.replaceChildren();

    const files = Array.from(input.files || []);
    previewSection.hidden = files.length === 0;
    files.forEach((file) => {
      previewGrid.appendChild(buildCard(file));
    });
  });
});