(function () {
  const root = document.querySelector('[data-product-search-root]');
  if (!root) {
    return;
  }

  const apiUrl = root.dataset.searchApiUrl;
  const heroInput = root.querySelector('#hero_search_q');
  const heroSearch = root.querySelector('.hero-search');
  const heroSuggestions = heroSearch ? heroSearch.querySelector('[data-search-suggestions]') : null;
  const categorySelect = root.querySelector('[data-search-category]');
  const navForm = document.querySelector('[data-product-search-form="nav"]');
  const navInput = navForm ? navForm.querySelector('[data-search-input]') : null;
  const navSuggestions = navForm ? navForm.querySelector('[data-search-suggestions]') : null;
  const navCategoryMirror = navForm ? navForm.querySelector('[data-search-category-mirror]') : null;
  const grid = document.querySelector('[data-product-grid]');
  const countBadge = document.querySelector('[data-product-count]');
  const heroSentinel = root.querySelector('[data-hero-search-sentinel]');
  const header = document.querySelector('.site-header');
  const inputs = [heroInput, navInput].filter(Boolean);
  const initialGridHtml = grid ? grid.innerHTML : '';
  const initialCountText = countBadge ? countBadge.textContent.trim() : '';
  let activeContainer = null;
  let activeItems = [];
  let activeIndex = -1;
  let debounceTimer = null;
  let pendingRequest = null;
  let observer = null;
  let scrollFrame = null;

  function setHeroSearchExpanded(isExpanded) {
    if (!heroSearch) {
      return;
    }
    heroSearch.classList.toggle('is-expanded', isExpanded);
  }

  function syncHeroDropdownOffset() {
    if (!heroSearch || !heroSuggestions) {
      return;
    }

    const isVisible = !heroSuggestions.hidden;
    const offset = isVisible ? heroSuggestions.offsetHeight : 0;
    heroSearch.style.setProperty('--hero-dropdown-offset', String(offset) + 'px');
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function pluralize(count) {
    return count === 1 ? 'product' : 'products';
  }

  function setCount(count) {
    if (!countBadge) {
      return;
    }
    countBadge.textContent = count + ' ' + pluralize(count);
  }

  function syncInputs(source) {
    inputs.forEach(function (input) {
      if (input !== source) {
        input.value = source.value;
      }
    });
  }

  function syncCategoryMirror() {
    if (navCategoryMirror && categorySelect) {
      navCategoryMirror.value = categorySelect.value;
    }
  }

  function clearSuggestions() {
    [heroSuggestions, navSuggestions].forEach(function (container) {
      if (!container) {
        return;
      }
      container.hidden = true;
      container.innerHTML = '';
    });
    activeContainer = null;
    activeItems = [];
    activeIndex = -1;
    setHeroSearchExpanded(false);
    syncHeroDropdownOffset();
  }

  function clearSuggestionContainer(container) {
    if (!container) {
      return;
    }

    container.hidden = true;
    container.innerHTML = '';

    if (container === activeContainer) {
      activeContainer = null;
      activeItems = [];
      activeIndex = -1;
    }

    if (container === heroSuggestions) {
      setHeroSearchExpanded(false);
      syncHeroDropdownOffset();
    }
  }

  function clearInactiveSuggestions(activeInput) {
    if (activeInput === navInput) {
      clearSuggestionContainer(heroSuggestions);
      return;
    }

    if (activeInput === heroInput) {
      clearSuggestionContainer(navSuggestions);
    }
  }

  function setActiveItem(nextIndex) {
    if (!activeItems.length) {
      return;
    }
    activeIndex = nextIndex;
    activeItems.forEach(function (item, index) {
      item.classList.toggle('is-active', index === activeIndex);
    });
  }

  function renderSuggestions(suggestions, container, query) {
    if (!container) {
      return;
    }

    clearSuggestionContainer(container === heroSuggestions ? navSuggestions : heroSuggestions);

    if (!query) {
      container.hidden = true;
      container.innerHTML = '';
      if (container === heroSuggestions) {
        setHeroSearchExpanded(false);
        syncHeroDropdownOffset();
      }
      return;
    }

    if (!suggestions.length) {
      container.innerHTML = '<div class="search-suggestion-empty">No matching products found.</div>';
      container.hidden = false;
      activeContainer = container;
      activeItems = [];
      activeIndex = -1;
      if (container === heroSuggestions) {
        setHeroSearchExpanded(true);
        syncHeroDropdownOffset();
      }
      return;
    }

    container.innerHTML = suggestions
      .map(function (suggestion, index) {
        return [
          '<a class="search-suggestion" href="',
          escapeHtml(suggestion.url),
          '" data-suggestion-index="',
          String(index),
          '">',
          '<span class="search-suggestion-copy">',
          '<span class="search-suggestion-label">',
          escapeHtml(suggestion.label),
          '</span>',
          '<span class="search-suggestion-meta">',
          escapeHtml(suggestion.meta),
          '</span>',
          '</span>',
          '<span class="search-suggestion-type">',
          escapeHtml(suggestion.type),
          '</span>',
          '</a>',
        ].join('');
      })
      .join('');

    container.hidden = false;
    activeContainer = container;
    activeItems = Array.from(container.querySelectorAll('.search-suggestion'));
    activeIndex = -1;
    if (container === heroSuggestions) {
      setHeroSearchExpanded(true);
      syncHeroDropdownOffset();
    }
  }

  function renderProducts(products) {
    if (!grid) {
      return;
    }

    if (!products.length) {
      grid.innerHTML = [
        '<div class="empty-state grid-column-full" data-empty-state>',
        '<i class="bi bi-search display-6 d-block mb-3" aria-hidden="true"></i>',
        '<h2 class="h4 text-dark">No products matched your filters.</h2>',
        '<p class="mb-0">Try another category, SKU, color, or finish.</p>',
        '</div>',
      ].join('');
      return;
    }

    grid.innerHTML = products
      .map(function (product) {
        const badgeClass = product.has_stock ? 'stock-in' : 'stock-out';
        const badgeText = product.has_stock ? 'In stock' : 'Ask in store';
        const priceText = product.starting_price ? 'WST ' + escapeHtml(product.starting_price) : 'Contact store';
        const imageMarkup = product.image_url
          ? '<img src="' + escapeHtml(product.image_url) + '" alt="' + escapeHtml(product.name) + '" loading="lazy">'
          : '<span>' + escapeHtml(product.category_name) + '</span>';

        return [
          '<article class="product-card">',
          '<a class="product-image" href="',
          escapeHtml(product.url),
          '" aria-label="View ',
          escapeHtml(product.name),
          '">',
          imageMarkup,
          '</a>',
          '<div class="product-body">',
          '<div class="d-flex justify-content-between align-items-start gap-2 mb-2">',
          '<span class="badge text-bg-light border">',
          escapeHtml(product.category_name),
          '</span>',
          '<span class="stock-badge ',
          badgeClass,
          '">',
          badgeText,
          '</span>',
          '</div>',
          '<h3 class="h5 mb-2"><a href="',
          escapeHtml(product.url),
          '">',
          escapeHtml(product.name),
          '</a></h3>',
          '<p class="text-secondary product-description mb-3">',
          escapeHtml(product.description),
          '</p>',
          '<div class="mt-auto d-flex justify-content-between align-items-center gap-3">',
          '<div><small class="text-secondary d-block">Starting at</small><strong class="fs-5">',
          priceText,
          '</strong></div>',
          '<a class="btn btn-accent" href="',
          escapeHtml(product.url),
          '">Choose</a>',
          '</div>',
          '</div>',
          '</article>',
        ].join('');
      })
      .join('');
  }

  function restoreInitialResults() {
    if (grid) {
      grid.innerHTML = initialGridHtml;
    }
    if (countBadge) {
      countBadge.textContent = initialCountText;
    }
    clearSuggestions();
  }

  function fetchResults(sourceInput) {
    const query = sourceInput.value.trim();
    const category = categorySelect ? categorySelect.value : '';
    syncInputs(sourceInput);
    syncCategoryMirror();
    clearInactiveSuggestions(sourceInput);

    if (!query && !category) {
      if (pendingRequest) {
        pendingRequest.abort();
      }
      restoreInitialResults();
      return;
    }

    if (pendingRequest) {
      pendingRequest.abort();
    }

    pendingRequest = new AbortController();
    const params = new URLSearchParams({ q: query, category: category });

    fetch(apiUrl + '?' + params.toString(), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: pendingRequest.signal,
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Search request failed');
        }
        return response.json();
      })
      .then(function (payload) {
        setCount(payload.count || 0);
        renderProducts(payload.products || []);
        renderSuggestions(payload.suggestions || [], sourceInput === navInput ? navSuggestions : heroSuggestions, query);
      })
      .catch(function (error) {
        if (error.name !== 'AbortError') {
          clearSuggestions();
        }
      });
  }

  function scheduleFetch(sourceInput) {
    clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(function () {
      fetchResults(sourceInput);
    }, 220);
  }

  function updateNavbarSearchState() {
    const isDesktop = window.matchMedia('(min-width: 992px)').matches;
    if (!isDesktop) {
      document.body.classList.remove('nav-search-active');
      return;
    }
    if (!heroSentinel) {
      return;
    }
    const topOffset = (header ? header.offsetHeight : 0) + 18;
    const shouldActivate = heroSentinel.getBoundingClientRect().top <= topOffset * -1;
    document.body.classList.toggle('nav-search-active', shouldActivate);
  }

  function setupObserver() {
    if (!heroSentinel) {
      return;
    }
    if (observer) {
      observer.disconnect();
    }

    observer = new IntersectionObserver(
      function (entries) {
        const entry = entries[0];
        const isDesktop = window.matchMedia('(min-width: 992px)').matches;
        document.body.classList.toggle('nav-search-active', isDesktop && !entry.isIntersecting);
      },
      {
        rootMargin: '-' + String((header ? header.offsetHeight : 0) + 24) + 'px 0px 0px 0px',
        threshold: 0.2,
      }
    );

    observer.observe(heroSentinel);
  }

  inputs.forEach(function (input) {
    input.addEventListener('focus', function () {
      clearInactiveSuggestions(input);
    });

    input.addEventListener('input', function () {
      scheduleFetch(input);
    });

    input.addEventListener('keydown', function (event) {
      if (!activeContainer || activeContainer.hidden) {
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!activeItems.length) {
          return;
        }
        setActiveItem((activeIndex + 1) % activeItems.length);
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (!activeItems.length) {
          return;
        }
        setActiveItem(activeIndex <= 0 ? activeItems.length - 1 : activeIndex - 1);
      }

      if (event.key === 'Enter' && activeIndex >= 0 && activeItems[activeIndex]) {
        event.preventDefault();
        window.location.href = activeItems[activeIndex].href;
      }

      if (event.key === 'Escape') {
        clearSuggestions();
      }
    });
  });

  if (categorySelect) {
    categorySelect.addEventListener('change', function () {
      syncCategoryMirror();
      fetchResults(heroInput || navInput);
    });
  }

  document.addEventListener('click', function (event) {
    const withinHero = heroSuggestions && heroSuggestions.contains(event.target);
    const withinNav = navSuggestions && navSuggestions.contains(event.target);
    const withinInputs = inputs.some(function (input) {
      return input === event.target;
    });
    const withinSearchControls = (heroSearch && heroSearch.contains(event.target)) || (navForm && navForm.contains(event.target));

    if (!withinHero && !withinNav && !withinInputs && !withinSearchControls) {
      clearSuggestions();
    }
  });

  window.addEventListener('resize', function () {
    syncCategoryMirror();
    setupObserver();
    updateNavbarSearchState();
  });

  window.addEventListener(
    'scroll',
    function () {
      if (scrollFrame) {
        return;
      }
      scrollFrame = window.requestAnimationFrame(function () {
        updateNavbarSearchState();
        scrollFrame = null;
      });
    },
    { passive: true }
  );

  syncCategoryMirror();
  setupObserver();
  updateNavbarSearchState();
})();