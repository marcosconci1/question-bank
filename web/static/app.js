(() => {
  'use strict';

  // State
  let currentUser = localStorage.getItem('qb_user') || 'marcos';
  let currentTheme = localStorage.getItem('qb_theme') || 'lamplight';
  let questionsBank = [];
  let userStats = null;
  let practiceTimer = null;
  let practiceStartTime = 0;

  // DOM Elements
  const app = document.getElementById('app');
  const userSelect = document.getElementById('user-select');
  const themeToggle = document.getElementById('theme-toggle');

  // Set Theme
  function applyTheme(theme) {
    currentTheme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('qb_theme', theme);
    themeToggle.textContent = theme === 'lamplight' ? 'daylight' : 'lamplight';
  }

  themeToggle.addEventListener('click', () => {
    applyTheme(currentTheme === 'lamplight' ? 'daylight' : 'lamplight');
  });
  applyTheme(currentTheme);

  // User Management
  async function loadUsers() {
    try {
      const res = await fetch('/api/users');
      const data = await res.json();
      const users = Array.isArray(data) ? data : (data.users || []);
      userSelect.innerHTML = '';

      if (!users.includes(currentUser) && currentUser) {
        const opt = document.createElement('option');
        opt.value = currentUser;
        opt.textContent = currentUser;
        userSelect.appendChild(opt);
      }

      for (const u of users) {
        const opt = document.createElement('option');
        opt.value = u;
        opt.textContent = u;
        if (u === currentUser) opt.selected = true;
        userSelect.appendChild(opt);
      }

      const newOpt = document.createElement('option');
      newOpt.value = '__new__';
      newOpt.textContent = '+ new user...';
      userSelect.appendChild(newOpt);
    } catch {
      // offline / quiet
    }
  }

  userSelect.addEventListener('change', async (e) => {
    const val = e.target.value;
    if (val === '__new__') {
      const name = window.prompt('Enter new username (lowercase letters, numbers, hyphens):');
      if (name) {
        const clean = name.trim();
        try {
          const res = await fetch('/api/users', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: clean})
          });
          if (res.ok) {
            currentUser = clean;
            localStorage.setItem('qb_user', currentUser);
            await loadUsers();
            userSelect.value = currentUser;
            renderRoute();
            return;
          } else {
            const err = await res.json();
            alert('Could not create user: ' + (err.message || err.error));
          }
        } catch (err) {
          alert('Network error creating user');
        }
      }
      userSelect.value = currentUser;
      return;
    }
    currentUser = val;
    localStorage.setItem('qb_user', currentUser);
    renderRoute();
  });

  // HTML escaping helper
  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Question Block Renderer
  function renderBlockOrContent(item) {
    if (typeof item === 'string') {
      return renderTextBlock(item);
    }
    if (Array.isArray(item)) {
      const container = document.createElement('div');
      container.className = 'block-list';
      for (const sub of item) {
        container.appendChild(renderBlockOrContent(sub));
      }
      return container;
    }
    if (item && typeof item === 'object') {
      if (item.type === 'text') {
        return renderTextBlock(item.content || '');
      } else if (item.type === 'image') {
        const img = document.createElement('img');
        let src = item.src || '';
        if (!src.startsWith('/') && !src.startsWith('data:')) {
          src = '/' + src;
        }
        img.src = src;
        img.alt = item.alt || 'Question illustration';
        img.className = 'question-image';
        return img;
      }
    }
    const fallback = document.createElement('span');
    fallback.textContent = String(item || '');
    return fallback;
  }

  function renderTextBlock(text) {
    const div = document.createElement('div');
    div.className = 'text-block';
    // Source data uses a trailing backslash as a Markdown line break; drop it.
    div.innerHTML = escapeHtml(String(text).replace(/\\(?=\r?\n|$)/g, ''));
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(div, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false}
          ],
          throwOnError: false
        });
      } catch {}
    }
    return div;
  }

  // Prettify tag label
  function prettifyTag(tag) {
    if (!tag) return '';
    const seg = tag.split('/').pop() || tag;
    const clean = seg.replace(/-/g, ' ').trim();
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  }

  // Heatmap helper
  function renderHeatmap(activity) {
    const container = document.createElement('div');
    container.className = 'heatmap-container';
    const grid = document.createElement('div');
    grid.className = 'heatmap-grid';

    if (!activity || !activity.length) {
      const empty = document.createElement('div');
      empty.className = 'quiet';
      empty.textContent = 'No practice activity recorded in the last 26 weeks.';
      return empty;
    }

    const maxCount = Math.max(1, ...activity.map(a => a.count || 0));

    for (const item of activity) {
      const cell = document.createElement('div');
      cell.className = 'heat-cell';
      const c = item.count || 0;
      if (c > 0) {
        const level = Math.min(4, Math.max(1, Math.ceil((c / maxCount) * 4)));
        cell.classList.add(`heat-${level}`);
      }
      cell.title = `${item.date}: ${c} answered`;
      grid.appendChild(cell);
    }

    container.appendChild(grid);
    return container;
  }

  // Session storage helper
  function getLocalSession() {
    try {
      const raw = localStorage.getItem(`qb_session_${currentUser}`);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function saveLocalSession(session) {
    if (!session) {
      localStorage.removeItem(`qb_session_${currentUser}`);
    } else {
      localStorage.setItem(`qb_session_${currentUser}`, JSON.stringify(session));
    }
  }

  // API calls
  async function fetchStats() {
    try {
      const res = await fetch(`/api/u/${currentUser}/stats`);
      if (res.ok) {
        return await res.json();
      }
    } catch {}
    return {total: 0, correct: 0, accuracy: 0.0, by_tag: [], activity: []};
  }

  async function fetchQuestions(params = {}) {
    try {
      const query = new URLSearchParams(params).toString();
      const res = await fetch(`/api/questions?${query}`);
      if (res.ok) {
        return await res.json();
      }
    } catch {}
    return [];
  }

  async function startNewSession(options = {}) {
    try {
      const res = await fetch(`/api/u/${currentUser}/sessions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(options)
      });
      if (!res.ok) {
        const err = await res.json();
        alert('Could not start session: ' + (err.message || err.error));
        return;
      }
      const data = await res.json();
      if (!data.question_ids || !data.question_ids.length) {
        alert('No questions found matching your selection.');
        return;
      }
      const session = {
        session_id: data.session_id,
        question_ids: data.question_ids,
        index: 0,
        options: options,
        results: [],
        completed: false
      };
      saveLocalSession(session);
      window.location.hash = '#/practice';
    } catch (err) {
      alert('Error creating session');
    }
  }

  // --- HOME SCREEN ---
  async function renderHome() {
    app.innerHTML = '<div class="quiet">Loading...</div>';

    const [stats, questions] = await Promise.all([
      fetchStats(),
      fetchQuestions({status: 'active'})
    ]);
    userStats = stats;
    questionsBank = questions;

    const exams = Array.from(new Set(questions.map(q => q.exam).filter(Boolean))).sort();
    const tags = Array.from(new Set(questions.flatMap(q => q.tags || []))).sort();

    app.innerHTML = '';

    // 1. Pick up where you left
    const localSession = getLocalSession();
    if (localSession && !localSession.completed && localSession.question_ids && localSession.question_ids.length) {
      const resumeSection = document.createElement('section');
      const h2 = document.createElement('h2');
      h2.textContent = 'Pick up where you left';
      resumeSection.appendChild(h2);

      const row = document.createElement('div');
      row.className = 'flat-row';
      const left = document.createElement('div');
      left.innerHTML = `<span class="badge-pinned">RESUME</span> <span>${escapeHtml(localSession.options?.tag ? prettifyTag(localSession.options.tag) : (localSession.options?.exam ? localSession.options.exam.toUpperCase() : 'Mixed'))} - ${localSession.index} of ${localSession.question_ids.length} answered</span>`;
      const right = document.createElement('a');
      right.href = '#/practice';
      right.textContent = 'Continue \u2192';
      row.appendChild(left);
      row.appendChild(right);
      resumeSection.appendChild(row);
      app.appendChild(resumeSection);
    }

    // 2. Start a session
    const startSection = document.createElement('section');
    const startH2 = document.createElement('h2');
    startH2.textContent = 'Start a session';
    startSection.appendChild(startH2);

    const sentence = document.createElement('div');
    sentence.className = 'inline-sentence';
    sentence.innerHTML = `Practice <select id="home-exam"><option value="">all exams</option>${exams.map(e => `<option value="${escapeHtml(e)}">${escapeHtml(e.toUpperCase())}</option>`).join('')}</select> questions on <select id="home-topic"><option value="__weakest__">my weakest topics</option><option value="">all topics</option>${tags.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(prettifyTag(t))}</option>`).join('')}</select>, <input type="number" id="home-count" value="10" min="1" max="50" style="width:3rem;"> at a time.`;
    startSection.appendChild(sentence);

    const checkDiv = document.createElement('div');
    checkDiv.className = 'form-checkboxes';
    checkDiv.innerHTML = `
      <label><input type="checkbox" id="home-suspended"> include suspended</label>
      <label><input type="checkbox" id="home-unseen"> only unseen</label>
    `;
    startSection.appendChild(checkDiv);

    const startBtn = document.createElement('button');
    startBtn.className = 'btn-primary';
    startBtn.textContent = 'Start practice';
    startBtn.addEventListener('click', () => {
      const examVal = document.getElementById('home-exam').value;
      const topicVal = document.getElementById('home-topic').value;
      const countVal = parseInt(document.getElementById('home-count').value, 10) || 10;
      const suspended = document.getElementById('home-suspended').checked;
      const unseen = document.getElementById('home-unseen').checked;

      const opts = {
        count: countVal,
        include_suspended: suspended,
        only_unseen: unseen
      };
      if (examVal) opts.exam = examVal;
      if (topicVal === '__weakest__') {
        opts.weakest = true;
      } else if (topicVal) {
        opts.tag = topicVal;
      }
      startNewSession(opts);
    });
    startSection.appendChild(startBtn);
    app.appendChild(startSection);

    // 3. Weak spots
    const weakSection = document.createElement('section');
    const weakH2 = document.createElement('h2');
    weakH2.textContent = 'Weak spots';
    weakSection.appendChild(weakH2);

    const weakRows = document.createElement('div');
    weakRows.className = 'flat-list';
    const topWeak = (stats.by_tag || []).slice(0, 5);
    if (!topWeak.length) {
      const empty = document.createElement('div');
      empty.className = 'quiet';
      empty.textContent = 'No weak spots identified yet. Practice some questions to see topics here.';
      weakRows.appendChild(empty);
    } else {
      for (const item of topWeak) {
        const row = document.createElement('div');
        row.className = 'flat-row';
        const link = document.createElement('a');
        link.textContent = item.label || prettifyTag(item.tag);
        link.href = '#/practice';
        link.addEventListener('click', (e) => {
          e.preventDefault();
          startNewSession({tag: item.tag, count: 10, only_unseen: true});
        });
        const num = document.createElement('span');
        num.className = 'quiet';
        const pct = Math.round(item.accuracy * 100);
        num.textContent = `${pct}% - ${item.total} answered`;
        row.appendChild(link);
        row.appendChild(num);
        weakRows.appendChild(row);
      }
    }
    weakSection.appendChild(weakRows);
    app.appendChild(weakSection);

    // 4. Activity
    const actSection = document.createElement('section');
    const actH2 = document.createElement('h2');
    actH2.textContent = 'Activity';
    actSection.appendChild(actH2);
    actSection.appendChild(renderHeatmap(stats.activity));
    app.appendChild(actSection);

    // 5. Footer line
    const footer = document.createElement('div');
    footer.className = 'footer-line quiet';
    const overallPct = Math.round((stats.accuracy || 0) * 100);
    footer.textContent = `${stats.total || 0} answered - ${overallPct}% correct - search with /`;
    app.appendChild(footer);
  }

  // --- PRACTICE SCREEN ---
  async function renderPractice() {
    let session = getLocalSession();
    if (!session || !session.question_ids || !session.question_ids.length) {
      app.innerHTML = `
        <h2>Practice</h2>
        <p class="quiet">No active session found.</p>
        <div style="margin-top:1.5rem;">
          <a href="#/" class="btn-primary">Return to Home</a>
        </div>
      `;
      return;
    }

    if (session.completed || session.index >= session.question_ids.length) {
      renderSessionSummary(session);
      return;
    }

    app.innerHTML = '<div class="quiet">Loading question...</div>';

    const qid = session.question_ids[session.index];
    let question = null;
    try {
      const res = await fetch(`/api/questions/${qid}`);
      if (res.ok) {
        question = await res.json();
      }
    } catch {}

    if (!question) {
      app.innerHTML = `
        <h2>Error</h2>
        <p class="quiet">Could not load question.</p>
        <p><a href="#/" class="door">Return to Home</a></p>
      `;
      return;
    }

    practiceStartTime = Date.now();
    app.innerHTML = '';

    // Header line: Exit left, n/N right
    const topBar = document.createElement('div');
    topBar.style.display = 'flex';
    topBar.style.justifyContent = 'space-between';
    topBar.style.alignItems = 'baseline';

    const exitLink = document.createElement('a');
    exitLink.href = '#/';
    exitLink.className = 'quiet';
    exitLink.textContent = '\u2715 Exit';
    topBar.appendChild(exitLink);

    const counter = document.createElement('span');
    counter.className = 'quiet ruda';
    counter.textContent = `${session.index + 1} / ${session.question_ids.length}`;
    topBar.appendChild(counter);
    app.appendChild(topBar);

    // Progress bar
    const progressTrack = document.createElement('div');
    progressTrack.className = 'progress-bar-track';
    const progressFill = document.createElement('div');
    progressFill.className = 'progress-bar-fill';
    progressFill.style.width = `${(session.index / session.question_ids.length) * 100}%`;
    progressTrack.appendChild(progressFill);
    app.appendChild(progressTrack);

    // Meta line
    const examStr = (question.exam || '').toUpperCase();
    const yearStr = question.year || '';
    const numStr = question.number ? `#${question.number}` : '';
    const topicLabel = prettifyTag((question.tags && question.tags[0]) || '');
    const metaLine = document.createElement('div');
    metaLine.className = 'quiet';
    metaLine.style.marginBottom = '1rem';
    metaLine.textContent = `${examStr} ${yearStr} - ${numStr} - ${topicLabel}`;
    app.appendChild(metaLine);

    // Question Text / Stem
    const stemBox = document.createElement('div');
    stemBox.className = 'question-text';
    stemBox.appendChild(renderBlockOrContent(question.stem));
    app.appendChild(stemBox);

    // Multiple Choice vs Discursive
    const isDiscursive = question.type === 'discursive' || !question.options;
    let selectedOption = null;
    let submitted = false;

    const feedbackArea = document.createElement('div');
    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn-primary btn-full';
    submitBtn.textContent = 'Submit';
    submitBtn.disabled = true;

    if (!isDiscursive) {
      const optionsContainer = document.createElement('div');
      optionsContainer.className = 'options-list';
      const letters = ['A', 'B', 'C', 'D', 'E'];
      const optRows = [];

      (question.options || []).forEach((opt, idx) => {
        const letter = letters[idx] || String.fromCharCode(65 + idx);
        const row = document.createElement('div');
        row.className = 'option-row';
        row.setAttribute('data-letter', letter);

        const letterSpan = document.createElement('span');
        letterSpan.className = 'option-letter';
        letterSpan.textContent = letter;

        const contentDiv = document.createElement('div');
        contentDiv.style.flex = '1';
        contentDiv.appendChild(renderBlockOrContent(opt));

        row.appendChild(letterSpan);
        row.appendChild(contentDiv);

        row.addEventListener('click', () => {
          if (submitted) return;
          for (const r of optRows) r.classList.remove('selected');
          row.classList.add('selected');
          selectedOption = letter;
          submitBtn.disabled = false;
        });

        optRows.push(row);
        optionsContainer.appendChild(row);
      });

      app.appendChild(optionsContainer);
      app.appendChild(feedbackArea);
      app.appendChild(submitBtn);

      // Keyboard handler for A-E and Enter
      window._practiceKeyHandler = (e) => {
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
        const key = e.key.toUpperCase();
        if (!submitted && ['A', 'B', 'C', 'D', 'E'].includes(key)) {
          const idx = key.charCodeAt(0) - 65;
          if (optRows[idx]) {
            for (const r of optRows) r.classList.remove('selected');
            optRows[idx].classList.add('selected');
            selectedOption = key;
            submitBtn.disabled = false;
          }
        } else if (e.key === 'Enter') {
          if (!submitted && selectedOption) {
            submitBtn.click();
          } else if (submitted) {
            submitBtn.click();
          }
        } else if (e.key.toUpperCase() === 'N' && submitted) {
          submitBtn.click();
        }
      };

      submitBtn.addEventListener('click', async () => {
        if (!submitted) {
          if (!selectedOption) return;
          submitted = true;
          submitBtn.disabled = true;
          const timeSpent = Math.max(1, Math.round((Date.now() - practiceStartTime) / 1000));

          try {
            const res = await fetch(`/api/u/${currentUser}/answer`, {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                question_id: qid,
                session_id: session.session_id,
                given_answer: selectedOption,
                time_spent: timeSpent
              })
            });
            const result = await res.json();
            if (!res.ok) {
              // Server refused (for example: this question is already recorded in this session).
              feedbackArea.innerHTML = '';
              const note = document.createElement('div');
              note.className = 'quiet';
              note.textContent = result.message || 'Could not record this answer.';
              feedbackArea.appendChild(note);
              if (result.error === 'already_recorded') {
                submitBtn.textContent = 'Next \u2192';
              } else {
                submitted = false;
              }
              submitBtn.disabled = false;
              return;
            }
            const isCorrect = result.is_correct;
            const correctAns = result.correct_answer;

            // Callout
            feedbackArea.innerHTML = '';
            const callout = document.createElement('div');
            callout.className = `callout ${isCorrect ? 'callout-correct' : 'callout-wrong'}`;
            if (isCorrect) {
              callout.innerHTML = `<div class="callout-title">\u2713 Correct</div>`;
            } else {
              callout.innerHTML = `
                <div class="callout-title">\u2717 Not quite - the answer is ${escapeHtml(correctAns)}</div>
                <div class="quiet">You chose ${escapeHtml(selectedOption)}</div>
              `;
            }
            feedbackArea.appendChild(callout);

            // Option states
            for (const r of optRows) {
              const lettr = r.getAttribute('data-letter');
              if (lettr === correctAns) {
                r.classList.add('opt-correct');
                const mark = document.createElement('span');
                mark.style.color = 'var(--success)';
                mark.style.fontWeight = '700';
                mark.textContent = ' \u2713';
                r.appendChild(mark);
              }
              if (!isCorrect && lettr === selectedOption) {
                r.classList.add('opt-wrong');
                const mark = document.createElement('span');
                mark.style.color = 'var(--failure)';
                mark.textContent = ' \u2717 you';
                r.appendChild(mark);
              }
            }

            // Quiet line: <topic> - seen Nx - P% correct
            const statLine = document.createElement('div');
            statLine.className = 'quiet';
            statLine.style.marginTop = '0.75rem';
            statLine.textContent = `${topicLabel} - practice attempt recorded`;
            feedbackArea.appendChild(statLine);

            // Save attempt
            session.results.push({
              qid: qid,
              given: selectedOption,
              correct: correctAns,
              is_correct: isCorrect,
              exam: question.exam,
              year: question.year,
              number: question.number
            });
            saveLocalSession(session);

            progressFill.style.width = `${((session.index + 1) / session.question_ids.length) * 100}%`;
            submitBtn.textContent = 'Next \u2192';
            submitBtn.disabled = false;
          } catch (err) {
            feedbackArea.innerHTML = '<div class="quiet">Could not reach the server. Try again.</div>';
            submitted = false;
            submitBtn.disabled = false;
          }
        } else {
          // Advance to next question
          session.index += 1;
          if (session.index >= session.question_ids.length) {
            session.completed = true;
          }
          saveLocalSession(session);
          renderPractice();
        }
      });
    } else {
      // Discursive Question
      const textarea = document.createElement('textarea');
      textarea.className = 'discursive-input';
      textarea.placeholder = 'Draft your answer here...';
      app.appendChild(textarea);

      const revealLink = document.createElement('a');
      revealLink.className = 'door';
      revealLink.style.display = 'inline-block';
      revealLink.style.marginBottom = '1rem';
      revealLink.textContent = 'Reveal rubric';
      app.appendChild(revealLink);

      const rubricBox = document.createElement('div');
      rubricBox.style.display = 'none';
      rubricBox.className = 'callout';
      app.appendChild(rubricBox);

      const gradeDiv = document.createElement('div');
      gradeDiv.className = 'grade-buttons';
      gradeDiv.style.display = 'none';
      gradeDiv.innerHTML = `
        <button class="btn-grade grade-correct" data-grade="correct">\u2713 Correct</button>
        <button class="btn-grade" data-grade="partial">Partial</button>
        <button class="btn-grade grade-wrong" data-grade="wrong">\u2717 Wrong</button>
      `;
      app.appendChild(gradeDiv);
      app.appendChild(feedbackArea);

      revealLink.addEventListener('click', async (e) => {
        e.preventDefault();
        revealLink.style.display = 'none';

        // Discursive grading
        const rubricContent = question.rubric || question.answer || 'Official rubric not provided.';
        rubricBox.innerHTML = '<div class="callout-title" style="margin-bottom:0.5rem;">Official Rubric</div>';
        rubricBox.appendChild(renderBlockOrContent(rubricContent));
        rubricBox.style.display = 'block';
        gradeDiv.style.display = 'flex';
      });

      gradeDiv.addEventListener('click', async (e) => {
        const btn = e.target.closest('button');
        if (!btn || submitted) return;
        submitted = true;
        const grade = btn.getAttribute('data-grade');
        const timeSpent = Math.max(1, Math.round((Date.now() - practiceStartTime) / 1000));

        try {
          const res = await fetch(`/api/u/${currentUser}/answer`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              question_id: qid,
              session_id: session.session_id,
              given_answer: textarea.value,
              self_grade: grade,
              time_spent: timeSpent
            })
          });
          const result = await res.json();
          const isCorrect = result.is_correct;

          session.results.push({
            qid: qid,
            given: grade,
            correct: 'rubric',
            is_correct: isCorrect,
            exam: question.exam,
            year: question.year,
            number: question.number
          });
          saveLocalSession(session);

          gradeDiv.style.display = 'none';
          submitBtn.textContent = 'Next \u2192';
          submitBtn.disabled = false;
          submitBtn.addEventListener('click', () => {
            session.index += 1;
            if (session.index >= session.question_ids.length) {
              session.completed = true;
            }
            saveLocalSession(session);
            renderPractice();
          });
          app.appendChild(submitBtn);
        } catch (err) {
          alert('Error recording self-grade');
          submitted = false;
        }
      });
    }

    // Bottom helper line: Skip & keyboard hint
    const bottomHelper = document.createElement('div');
    bottomHelper.style.display = 'flex';
    bottomHelper.style.justifyContent = 'space-between';
    bottomHelper.style.marginTop = '0.75rem';
    bottomHelper.className = 'quiet';

    const skipLink = document.createElement('a');
    skipLink.className = 'quiet';
    skipLink.textContent = 'Skip';
    skipLink.addEventListener('click', (e) => {
      e.preventDefault();
      session.index += 1;
      if (session.index >= session.question_ids.length) {
        session.completed = true;
      }
      saveLocalSession(session);
      renderPractice();
    });

    const kbHint = document.createElement('span');
    kbHint.textContent = isDiscursive ? '' : '[A-E] select \u2022 [Enter] submit';

    bottomHelper.appendChild(skipLink);
    bottomHelper.appendChild(kbHint);
    app.appendChild(bottomHelper);
  }

  function renderSessionSummary(session) {
    const total = session.results.length;
    const correct = session.results.filter(r => r.is_correct).length;
    const wrongs = session.results.filter(r => !r.is_correct);

    app.innerHTML = '';
    const h2 = document.createElement('h2');
    h2.textContent = `${correct} of ${total} correct`;
    app.appendChild(h2);

    if (wrongs.length) {
      const p = document.createElement('p');
      p.className = 'quiet';
      p.textContent = 'Review questions answered incorrectly:';
      app.appendChild(p);

      const list = document.createElement('div');
      list.className = 'flat-list';
      for (const w of wrongs) {
        const row = document.createElement('div');
        row.className = 'flat-row';
        const link = document.createElement('a');
        link.textContent = `${(w.exam || '').toUpperCase()} ${w.year || ''} #${w.number || ''} (${w.qid})`;
        link.href = `#/search`;
        link.addEventListener('click', (e) => {
          e.preventDefault();
          renderQuestionReadOnly(w.qid);
        });
        const ansInfo = document.createElement('span');
        ansInfo.className = 'quiet';
        ansInfo.textContent = `Chose ${w.given}, answer was ${w.correct}`;
        row.appendChild(link);
        row.appendChild(ansInfo);
        list.appendChild(row);
      }
      app.appendChild(list);
    } else {
      const p = document.createElement('p');
      p.className = 'quiet';
      p.textContent = 'Great job! All questions in this session were answered correctly.';
      app.appendChild(p);
    }

    const retP = document.createElement('p');
    retP.style.marginTop = '2rem';
    const retLink = document.createElement('a');
    retLink.className = 'btn-primary';
    retLink.href = '#/';
    retLink.textContent = 'Return to Home';
    retP.appendChild(retLink);
    app.appendChild(retP);

    // Clear completed session from local storage
    localStorage.removeItem(`qb_session_${currentUser}`);
  }

  // --- SEARCH SCREEN ---
  async function renderSearch() {
    app.innerHTML = `
      <h2>Search</h2>
      <div class="search-bar">
        <input type="text" id="search-input" class="search-input" placeholder="Search questions by topic, concept, or keywords..." autofocus>
        <div class="search-filters">
          <select id="search-exam"><option value="">all exams</option><option value="poscomp">POSCOMP</option><option value="enade">ENADE</option></select>
          <input type="number" id="search-year" placeholder="Year" style="width:5rem; background:transparent; border:none; border-bottom:1px solid var(--quiet); color:var(--ink); padding:2px 4px; outline:none;">
        </div>
      </div>
      <div id="search-results" class="flat-list"></div>
    `;

    const input = document.getElementById('search-input');
    const examSelect = document.getElementById('search-exam');
    const yearInput = document.getElementById('search-year');
    const resultsContainer = document.getElementById('search-results');

    let debounceTimer = null;
    function doSearch() {
      const q = input.value.trim();
      if (!q) {
        resultsContainer.innerHTML = '';
        return;
      }
      resultsContainer.innerHTML = '<div class="quiet">Searching...</div>';

      const params = new URLSearchParams({q: q});
      if (examSelect.value) params.set('exam', examSelect.value);
      if (yearInput.value) params.set('year', yearInput.value);

      fetch(`/api/search?${params.toString()}`)
        .then(async (res) => {
          if (res.status === 503) {
            const err = await res.json();
            resultsContainer.innerHTML = `<div class="quiet">Search is currently unavailable: ${escapeHtml(err.message || 'offline')}</div>`;
            return;
          }
          if (!res.ok) {
            resultsContainer.innerHTML = '<div class="quiet">Search encountered an error.</div>';
            return;
          }
          const items = await res.json();
          resultsContainer.innerHTML = '';
          if (!items.length) {
            resultsContainer.innerHTML = '<div class="quiet">No questions found matching your search.</div>';
            return;
          }
          for (const item of items) {
            const row = document.createElement('div');
            row.className = 'flat-row';
            row.style.cursor = 'pointer';
            row.style.flexDirection = 'column';
            row.style.alignItems = 'flex-start';

            const header = document.createElement('div');
            header.style.display = 'flex';
            header.style.justifyContent = 'space-between';
            header.style.width = '100%';

            const link = document.createElement('a');
            link.textContent = `${(item.exam || '').toUpperCase()} ${item.year || ''} ${item.number ? '#' + item.number : ''}`;
            const meta = document.createElement('span');
            meta.className = 'quiet';
            meta.textContent = `${item.id} \u2022 score: ${item.score}`;
            header.appendChild(link);
            header.appendChild(meta);

            const snippet = document.createElement('div');
            snippet.className = 'quiet';
            snippet.style.fontSize = '0.9rem';
            snippet.style.marginTop = '0.25rem';
            snippet.textContent = item.snippet;

            row.appendChild(header);
            row.appendChild(snippet);

            row.addEventListener('click', () => {
              renderQuestionReadOnly(item.id);
            });
            resultsContainer.appendChild(row);
          }
        })
        .catch(() => {
          resultsContainer.innerHTML = '<div class="quiet">Search is currently unavailable.</div>';
        });
    }

    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(doSearch, 300);
    });
    examSelect.addEventListener('change', doSearch);
    yearInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(doSearch, 400);
    });

    input.focus();
  }

  async function renderQuestionReadOnly(qid) {
    app.innerHTML = '<div class="quiet">Loading question...</div>';
    let question = null;
    try {
      const res = await fetch(`/api/questions/${qid}`);
      if (res.ok) question = await res.json();
    } catch {}

    if (!question) {
      app.innerHTML = '<div class="quiet">Question not found.</div>';
      return;
    }

    app.innerHTML = '';
    const topBar = document.createElement('div');
    topBar.style.display = 'flex';
    topBar.style.justifyContent = 'space-between';
    topBar.style.marginBottom = '1rem';

    const back = document.createElement('a');
    back.className = 'quiet';
    back.textContent = '\u2190 Back to search';
    back.href = '#/search';
    topBar.appendChild(back);

    const prac = document.createElement('a');
    prac.textContent = 'Practice this question \u2192';
    prac.href = '#/practice';
    prac.addEventListener('click', (e) => {
      e.preventDefault();
      saveLocalSession({
        session_id: 's_' + Date.now(),
        question_ids: [qid],
        index: 0,
        options: {},
        results: [],
        completed: false
      });
      window.location.hash = '#/practice';
    });
    topBar.appendChild(prac);
    app.appendChild(topBar);

    const title = document.createElement('div');
    title.className = 'quiet';
    title.style.marginBottom = '0.5rem';
    title.textContent = `${(question.exam || '').toUpperCase()} ${question.year || ''} #${question.number || ''} (${question.id})`;
    app.appendChild(title);

    const stemBox = document.createElement('div');
    stemBox.className = 'question-text';
    stemBox.appendChild(renderBlockOrContent(question.stem));
    app.appendChild(stemBox);

    if (question.options) {
      const opts = document.createElement('div');
      opts.className = 'options-list';
      const letters = ['A', 'B', 'C', 'D', 'E'];
      question.options.forEach((opt, idx) => {
        const row = document.createElement('div');
        row.className = 'option-row';
        const letSpan = document.createElement('span');
        letSpan.className = 'option-letter';
        letSpan.textContent = letters[idx] || '';
        const body = document.createElement('div');
        body.appendChild(renderBlockOrContent(opt));
        row.appendChild(letSpan);
        row.appendChild(body);
        opts.appendChild(row);
      });
      app.appendChild(opts);
    }

    const showAnsP = document.createElement('p');
    showAnsP.style.marginTop = '1.5rem';
    const showAnsLink = document.createElement('a');
    showAnsLink.className = 'door';
    showAnsLink.textContent = 'Show answer';
    showAnsP.appendChild(showAnsLink);
    app.appendChild(showAnsP);

    const ansArea = document.createElement('div');
    ansArea.style.display = 'none';
    ansArea.className = 'callout';
    app.appendChild(ansArea);

    showAnsLink.addEventListener('click', (e) => {
      e.preventDefault();
      showAnsLink.style.display = 'none';
      ansArea.innerHTML = '<div class="callout-title">Answer</div><p class="quiet">Answers are withheld on the client. Practice this question to test your knowledge.</p>';
      ansArea.style.display = 'block';
    });
  }

  // --- STATS SCREEN ---
  async function renderStats() {
    app.innerHTML = '<div class="quiet">Loading stats...</div>';
    const stats = await fetchStats();
    app.innerHTML = '';

    const h2 = document.createElement('h2');
    h2.textContent = 'Statistics';
    app.appendChild(h2);

    const overallPct = Math.round((stats.accuracy || 0) * 100);
    const overall = document.createElement('p');
    overall.className = 'quiet';
    overall.style.marginBottom = '1.5rem';
    overall.textContent = `Total: ${stats.total || 0} answered \u2022 ${stats.correct || 0} correct \u2022 ${overallPct}% accuracy`;
    app.appendChild(overall);

    const actH3 = document.createElement('h3');
    actH3.textContent = 'Activity';
    actH3.style.fontSize = '1.05rem';
    actH3.style.marginTop = '1.5rem';
    actH3.style.marginBottom = '0.5rem';
    app.appendChild(actH3);
    app.appendChild(renderHeatmap(stats.activity));

    const topH3 = document.createElement('h3');
    topH3.textContent = 'Topic Performance';
    topH3.style.fontSize = '1.05rem';
    topH3.style.marginTop = '2rem';
    topH3.style.marginBottom = '0.5rem';
    app.appendChild(topH3);

    const list = document.createElement('div');
    list.className = 'flat-list';
    if (!stats.by_tag || !stats.by_tag.length) {
      const empty = document.createElement('div');
      empty.className = 'quiet';
      empty.textContent = 'No answer records yet.';
      list.appendChild(empty);
    } else {
      for (const item of stats.by_tag) {
        const row = document.createElement('div');
        row.className = 'flat-row';
        const link = document.createElement('a');
        link.textContent = item.label || prettifyTag(item.tag);
        link.href = '#/practice';
        link.addEventListener('click', (e) => {
          e.preventDefault();
          startNewSession({tag: item.tag, count: 10, only_unseen: true});
        });

        const score = document.createElement('span');
        score.className = 'quiet';
        const pct = Math.round(item.accuracy * 100);
        score.textContent = `${pct}% (${item.correct}/${item.total})`;

        row.appendChild(link);
        row.appendChild(score);
        list.appendChild(row);
      }
    }
    app.appendChild(list);
  }

  // Router
  function updateNavActive(route) {
    document.querySelectorAll('.nav-links a').forEach(a => a.classList.remove('active'));
    if (route === '/practice') {
      const el = document.getElementById('nav-practice');
      if (el) el.classList.add('active');
    } else if (route === '/search') {
      const el = document.getElementById('nav-search');
      if (el) el.classList.add('active');
    } else if (route === '/stats') {
      const el = document.getElementById('nav-stats');
      if (el) el.classList.add('active');
    }
  }

  function renderRoute() {
    window._practiceKeyHandler = null;
    const hash = window.location.hash || '#/';
    const path = hash.replace(/^#/, '') || '/';

    updateNavActive(path);

    if (path === '/' || path === '') {
      renderHome();
    } else if (path === '/practice') {
      renderPractice();
    } else if (path === '/search') {
      renderSearch();
    } else if (path === '/stats') {
      renderStats();
    } else {
      renderHome();
    }
  }

  window.addEventListener('hashchange', renderRoute);

  // Global keydown handler
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    if (e.key === '/') {
      e.preventDefault();
      if (window.location.hash !== '#/search') {
        window.location.hash = '#/search';
      } else {
        const inp = document.getElementById('search-input');
        if (inp) inp.focus();
      }
      return;
    }
    if (window._practiceKeyHandler) {
      window._practiceKeyHandler(e);
    }
  });

  // Init
  loadUsers().then(() => {
    renderRoute();
  });
})();
