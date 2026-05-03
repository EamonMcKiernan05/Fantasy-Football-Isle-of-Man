/**
 * Fantasy Football Isle of Man - FPL-style fantasy football
 *
 * Frontend logic for: Pick Team, Transfers, Gameweeks, History, Dream Team.
 */

const API_BASE = '/api';
let currentUser = null;
let currentTeam = null;
let currentSquad = [];
let allGameweeks = [];
let countdownInterval = null;

// Transfer page state
let pendingTransfers = []; // [{outId, inPlayer}]
let selectedOutPlayer = null; // squad player chosen to drop
let transferPlayersCache = [];

// ===== AUTH =====
function getToken() { return localStorage.getItem('token'); }

async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}${url}`, { ...options, headers });
    if (response.status === 401) {
        logout();
        throw new Error('Unauthorized');
    }
    return response;
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    try {
        const response = await fetch(`${API_BASE}/users/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
        });
        if (!response.ok) {
            const err = await response.json();
            return showToast(err.detail || 'Login failed', 'error');
        }
        const data = await response.json();
        localStorage.setItem('token', data.access_token);
        currentUser = data.user;
        await loadTeam();
        updateNav();
        navigate('my-team');
    } catch (err) {
        showToast('Login failed: ' + err.message, 'error');
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const teamName = document.getElementById('reg-team-name').value;
    try {
        const response = await fetch(`${API_BASE}/users/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password, team_name: teamName }),
        });
        if (!response.ok) {
            const err = await response.json();
            return showToast(err.detail || 'Registration failed', 'error');
        }
        const data = await response.json();
        localStorage.setItem('token', data.access_token);
        currentUser = data.user;
        currentTeam = data.team;
        updateNav();
        showToast('Account created! Pick your squad on the Transfers page.', 'success');
        navigate('transfers');
    } catch (err) {
        showToast('Registration failed: ' + err.message, 'error');
    }
}

function logout() {
    localStorage.removeItem('token');
    currentUser = null;
    currentTeam = null;
    currentSquad = [];
    updateNav();
    navigate('home');
}

function updateNav() {
    const authDiv = document.getElementById('nav-auth');
    if (currentUser) {
        authDiv.innerHTML = `
            <span class="nav-user">${escapeHtml(currentUser.username)}</span>
            <button class="btn btn-sm btn-outline" onclick="logout()">Logout</button>`;
    } else {
        authDiv.innerHTML = `<button class="btn btn-sm btn-primary" onclick="navigate('login')">Login</button>`;
    }
}

// ===== NAVIGATION =====
function navigate(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');
    const navLink = document.querySelector(`.nav-link[data-page="${page}"]`);
    if (navLink) navLink.classList.add('active');

    switch (page) {
        case 'home': loadHomePage(); break;
        case 'my-team': loadMyTeam(); break;
        case 'transfers': loadTransfersPage(); break;
        case 'players': loadPlayers(); break;
        case 'fixtures': loadFixtures(); break;
        case 'gameweeks': loadGameweeks(); break;
        case 'history': loadHistoryPage(); break;
        case 'leaderboard': loadLeaderboard(); break;
        case 'dream-team': loadDreamTeamPage(); break;
        case 'leagues': loadLeagues(); break;
        case 'notifications': loadNotifications(); break;
    }
}

// ===== HOME =====
async function loadHomePage() { await loadGameweekBanner(); }

async function loadGameweekBanner() {
    const banner = document.getElementById('gw-banner');
    if (!banner) return;
    try {
        const response = await apiFetch('/gameweek-history/current-gw-info');
        if (!response.ok) { banner.innerHTML = ''; return; }
        const data = await response.json();
        if (data.status === 'no_gameweeks') {
            banner.innerHTML = '<div class="gw-banner-card"><p>No gameweeks configured yet.</p></div>';
            return;
        }
        if (data.status === 'season_not_started') {
            banner.innerHTML = `
                <div class="gw-banner-card">
                    <h3>Season Not Started</h3>
                    <p>Gameweek ${data.next_gameweek} is next.</p>
                </div>`;
            return;
        }
        banner.innerHTML = `
            <div class="gw-banner-card">
                <div class="gw-banner-left">
                    <h3>Gameweek ${data.gameweek_number}</h3>
                    <p class="gw-deadline">Deadline: ${formatDateTime(data.deadline)}</p>
                    ${data.is_closed ? '<span class="badge badge-closed">Deadline Passed</span>' : ''}
                </div>
                <div class="gw-banner-right">
                    <div class="gw-countdown" id="gw-countdown">
                        ${data.is_closed ? 'Closed' : data.time_remaining_formatted}
                    </div>
                    ${data.is_scored ? '<span class="badge badge-scored">Scored</span>' : ''}
                </div>
            </div>`;
        startCountdown(data.deadline_unix);
    } catch (err) {
        console.error('Failed to load GW banner:', err);
    }
}

function startCountdown(deadlineUnix) {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
        const el = document.getElementById('gw-countdown');
        if (!el) { clearInterval(countdownInterval); return; }
        const now = Math.floor(Date.now() / 1000);
        const remaining = deadlineUnix - now;
        if (remaining <= 0) {
            el.textContent = 'Closed';
            clearInterval(countdownInterval);
            return;
        }
        el.textContent = formatCountdown(remaining);
    }, 1000);
}

function formatCountdown(s) {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const parts = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0 || d > 0) parts.push(`${h}h`);
    parts.push(`${m}m`);
    parts.push(`${sec}s`);
    return parts.join(' ');
}

// ===== TEAM (PICK TEAM / MY TEAM) =====
async function loadMyTeam() {
    if (!currentUser) return navigate('login');
    await loadTeam();
    await renderMyTeam();
}

async function loadTeam() {
    try {
        const response = await apiFetch('/users/me');
        if (!response.ok) return;
        const data = await response.json();
        currentTeam = data.team;
        currentUser = data.user;
        if (currentTeam) {
            const sq = await apiFetch(`/users/${currentTeam.id}/squad`);
            if (sq.ok) currentSquad = await sq.json();
        }
        updateNav();
    } catch (err) {
        console.error('loadTeam', err);
    }
}

async function renderMyTeam() {
    if (!currentTeam) {
        document.getElementById('page-my-team').innerHTML = `
            <div class="empty-state">
                <h3>No team yet</h3>
                <p>Create an account or log in to manage your team.</p>
            </div>`;
        return;
    }

    const totalValue = currentSquad.reduce((s, sp) => s + (sp.player?.price || 0), 0);
    document.getElementById('team-name').textContent = currentTeam.name;
    document.getElementById('team-budget').textContent = `£${(currentTeam.budget_remaining || 0).toFixed(1)}m`;
    document.getElementById('team-value').textContent = totalValue.toFixed(1);
    document.getElementById('team-points').textContent = currentTeam.total_points || 0;
    document.getElementById('team-transfers').textContent =
        `${currentTeam.current_gw_transfers || 0} / FT ${currentTeam.free_transfers || 0}`;

    if (currentSquad.length < 13) {
        const pitchPlayers = document.getElementById('pitch-players');
        if (pitchPlayers) {
            pitchPlayers.innerHTML = `
                <div class="pitch-empty">
                    <h3>Squad incomplete (${currentSquad.length}/13)</h3>
                    <p>Head to the <a href="#" onclick="navigate('transfers')">Transfers</a> tab to pick your squad.</p>
                </div>`;
        }
        document.getElementById('bench-grid').innerHTML = '';
        renderChips();
        return;
    }

    renderPitch(currentSquad);
    renderBench(currentSquad);
    renderChips();
    renderChipStatusBar();
}

// Formation functions removed - no position restrictions

function renderChipStatusBar() {
    const bar = document.getElementById('chip-status-bar');
    if (!bar) return;
    if (currentTeam.active_chip) {
        const names = { wildcard: 'Wildcard', free_hit: 'Free Hit', bench_boost: 'Bench Boost', triple_captain: 'Triple Captain' };
        bar.innerHTML = `
            <div class="chip-active-banner">
                <span class="chip-active-icon">⚡</span>
                <span><strong>${names[currentTeam.active_chip]}</strong> active for this gameweek</span>
                ${currentTeam.active_chip !== 'free_hit'
                    ? `<button class="btn btn-sm btn-outline" onclick="cancelActiveChip('${currentTeam.active_chip}')">Cancel</button>`
                    : ''}
            </div>`;
    } else {
        bar.innerHTML = '';
    }
}

function renderPitch(squad) {
    const pitchPlayers = document.getElementById('pitch-players');
    if (!pitchPlayers) return;
    const starters = squad.filter(sp => sp.is_starting);

    let html = '';
    // 2-3-2-3 layout for 10 starters
    const rows = [
        { players: starters.slice(0, 2), top: 20 },
        { players: starters.slice(2, 5), top: 40 },
        { players: starters.slice(5, 7), top: 60 },
        { players: starters.slice(7, 10), top: 80 },
    ];
    for (const row of rows) {
        html += renderPitchRow(row.players, row.top);
    }
    pitchPlayers.innerHTML = html;
}

function renderPitchRow(players, topPercent) {
    if (!players.length) return '';
    const items = players.map((sp, i) => {
        const xPct = (100 / (players.length + 1)) * (i + 1);
        return renderPitchPlayer(sp, xPct, topPercent);
    }).join('');
    return `<div class="pitch-row" style="top:${topPercent}%">${items}</div>`;
}

function renderPitchPlayer(sp, xPct, topPct) {
    const teamName = sp.player?.team?.name || '';
    const captainBadge = sp.is_captain ? '<div class="captain-badge">C</div>'
        : sp.is_vice_captain ? '<div class="vice-captain-badge">V</div>' : '';
    const points = sp.gw_points != null ? sp.gw_points : '–';
    const injured = sp.player?.is_injured ? '<span class="injury-dot" title="Injured/Doubt">!</span>' : '';
    const gradient = shirtGradient(teamName);
    const gradientLight = shirtGradientLight(teamName);
    const clickHandler = `showPlayerMenu(${sp.id}, ${sp.player_id})`;
    return `
        <div class="pitch-slot" style="left:${xPct}%" onclick="${clickHandler}">
            <div class="player-card fpl-card" onclick="${clickHandler}" style="--shirt-dark:${gradient};--shirt-light:${gradientLight}">
                ${captainBadge}
                ${injured}
                <div class="fpl-shirt" style="background-image:url(${shirtIcon(teamName)})"></div>
                <div class="fpl-player-name">${escapeHtml(sp.player?.name || '?')}</div>
                <div class="fpl-player-team">${escapeHtml(teamName)}</div>
                <div class="fpl-player-points">${points}</div>
            </div>
        </div>`;
}

function renderBench(squad) {
    const benchGrid = document.getElementById('bench-grid');
    if (!benchGrid) return;
    const bench = squad.filter(sp => !sp.is_starting)
        .sort((a, b) => (a.bench_priority || 99) - (b.bench_priority || 99));

    benchGrid.innerHTML = bench.map((sp, idx) => {
        const teamName = sp.player?.team?.name || '';
        const gradient = shirtGradient(teamName);
        const gradientLight = shirtGradientLight(teamName);
        return `
            <div class="bench-slot" onclick="showPlayerMenu(${sp.id}, ${sp.player_id})">
                <div class="bench-slot-num">SUB ${idx + 1}</div>
                <div class="player-card fpl-card bench-card">
                    <div class="fpl-shirt" style="background-image:url(${shirtIcon(teamName)})"></div>
                    <div class="fpl-player-name">${escapeHtml(sp.player?.name || '?')}</div>
                    <div class="fpl-player-team">${escapeHtml(teamName)}</div>
                    <div class="fpl-player-points">${sp.gw_points != null ? sp.gw_points : '–'}</div>
                </div>
            </div>`;
    }).join('');
}

// changeFormation removed - no formation selector

// ===== PLAYER MENU (captain / VC / bench / start / info) =====
async function showPlayerMenu(squadId, playerId) {
    const sp = currentSquad.find(s => s.id === squadId);
    if (!sp) return;

    const isStarter = sp.is_starting;
    const benchLabel = isStarter ? 'Substitute (bench)' : 'Substitute (start)';

    const overlay = document.getElementById('modal-overlay');
    const content = document.getElementById('modal-content');
    content.style.display = 'block';
    content.style.maxWidth = '380px';
    content.innerHTML = `
        <div class="player-menu-modal">
            <h3>${escapeHtml(sp.player?.name || 'Player')}</h3>
            <p class="muted">${escapeHtml(sp.player?.team?.name || '')} · £${(sp.player?.price || 0).toFixed(1)}m</p>
            <div class="menu-actions">
                ${isStarter && !sp.is_captain ? `<button class="btn btn-block btn-outline" data-action="captain" data-squad="${squadId}">Make Captain</button>` : ''}
                ${isStarter && !sp.is_vice_captain ? `<button class="btn btn-block btn-outline" data-action="vice-captain" data-squad="${squadId}">Make Vice-Captain</button>` : ''}
                <button class="btn btn-block btn-outline" data-action="${isStarter ? 'bench' : 'start'}" data-squad="${squadId}">${benchLabel}</button>
                <button class="btn btn-block btn-outline" data-action="detail" data-player="${playerId}">View player info</button>
                <button class="btn btn-block btn-secondary" data-action="close">Close</button>
            </div>
        </div>`;
    overlay.style.display = 'block';

    // Attach event listeners to buttons
    content.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', async function(e) {
            e.stopPropagation();
            const action = this.dataset.action;
            const squadId = parseInt(this.dataset.squad);
            const playerId = parseInt(this.dataset.player);

            switch (action) {
                case 'captain':
                    await setCaptain(squadId);
                    break;
                case 'vice-captain':
                    await setViceCaptain(squadId);
                    break;
                case 'bench':
                    await benchPlayer(squadId);
                    break;
                case 'start':
                    await startPlayer(squadId);
                    break;
                case 'detail':
                    closeModal();
                    await showPlayerDetail(playerId);
                    return; // Don't close modal again
                case 'close':
                    break;
            }
            closeModal();
        });
    });
}

function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    const content = document.getElementById('modal-content');
    if (overlay) overlay.style.display = 'none';
    if (content) content.style.display = 'none';
}

// Click on overlay (dark area) closes modal
document.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') closeModal();
});

async function setCaptain(squadId) {
    const r = await apiFetch(`/users/${currentTeam.id}/captain/${squadId}`, { method: 'POST' });
    if (r.ok) {
        showToast('Captain set', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}
async function setViceCaptain(squadId) {
    const r = await apiFetch(`/users/${currentTeam.id}/vice-captain/${squadId}`, { method: 'POST' });
    if (r.ok) {
        showToast('Vice-captain set', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}
async function benchPlayer(squadId) {
    const r = await apiFetch(`/users/${currentTeam.id}/squad/${squadId}/bench`, { method: 'POST' });
    if (r.ok) {
        showToast('Substituted', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}
async function startPlayer(squadId) {
    const r = await apiFetch(`/users/${currentTeam.id}/squad/${squadId}/start`, { method: 'POST' });
    if (r.ok) {
        showToast('Promoted to XI', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}

// ===== CHIPS =====
async function renderChips() {
    if (!currentTeam) return;
    const chipsGrid = document.getElementById('chips-grid');
    if (!chipsGrid) return;

    try {
        const r = await apiFetch(`/users/${currentTeam.id}/chips`);
        if (!r.ok) return;
        const chips = await r.json();
        const icons = { wildcard: '🃏', free_hit: '⚡', bench_boost: '📈', triple_captain: '🎯' };
        const names = { wildcard: 'Wildcard', free_hit: 'Free Hit', bench_boost: 'Bench Boost', triple_captain: 'Triple Captain' };
        const desc = {
            wildcard: 'Unlimited free transfers',
            free_hit: 'One-off squad change, reverts',
            bench_boost: 'All 13 players score',
            triple_captain: 'Captain scores 3× instead of 2×',
        };
        chipsGrid.innerHTML = chips.map(c => {
            const status = c.active ? 'active' : (c.available ? 'available' : 'used');
            const half = c.current_half === 'first' ? '1st half' : '2nd half';
            const label = c.active ? 'ACTIVE' : c.available ? `Available (${half})` : `Used (${half})`;
            return `
                <div class="chip-card chip-${c.type} chip-${status}">
                    <div class="chip-icon">${icons[c.type]}</div>
                    <div class="chip-name">${names[c.type]}</div>
                    <div class="chip-desc">${desc[c.type]}</div>
                    <div class="chip-status">${label}</div>
                    <div class="chip-halves">
                        <span class="chip-half ${c.first_half_used ? 'used' : ''}">1st</span>
                        <span class="chip-half ${c.second_half_used ? 'used' : ''}">2nd</span>
                    </div>
                    ${c.active && c.type !== 'free_hit'
                        ? `<button class="btn btn-sm btn-danger" onclick="cancelActiveChip('${c.type}')">Cancel</button>`
                        : c.available && !c.active
                            ? `<button class="btn btn-sm btn-success" onclick="confirmChipActivation('${c.type}')">Activate</button>`
                            : ''}
                </div>`;
        }).join('');
    } catch (err) {
        console.error('chips', err);
    }
}

function confirmChipActivation(chipType) {
    const names = { wildcard: 'Wildcard', free_hit: 'Free Hit', bench_boost: 'Bench Boost', triple_captain: 'Triple Captain' };
    const isFreeHit = chipType === 'free_hit';
    const overlay = document.getElementById('modal-overlay');
    const content = document.getElementById('modal-content');
    content.style.display = 'block';
    content.style.maxWidth = '420px';
    content.innerHTML = `
        <div class="chip-confirm-modal">
            <h3>Play ${names[chipType]}?</h3>
            ${isFreeHit
                ? '<p class="warning-text">Free Hit cannot be cancelled once confirmed.</p>'
                : '<p class="muted">You can cancel this chip before the deadline.</p>'}
            <div class="chip-confirm-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-success" onclick="activateChip('${chipType}'); closeModal()">Confirm</button>
            </div>
        </div>`;
    overlay.style.display = 'block';
}

async function activateChip(chipType) {
    const r = await apiFetch(`/users/${currentTeam.id}/chips/activate/${chipType}`, { method: 'POST' });
    if (r.ok) {
        showToast('Chip activated', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}
async function cancelActiveChip(chipType) {
    const r = await apiFetch(`/users/${currentTeam.id}/chips/cancel/${chipType}`, { method: 'POST' });
    if (r.ok) {
        showToast('Chip cancelled', 'success');
        await loadMyTeam();
    } else {
        const err = await r.json();
        showToast(err.detail || 'Failed', 'error');
    }
}

// ===== TRANSFERS =====
async function loadTransfersPage() {
    if (!currentUser) return navigate('login');
    await loadTeam();
    pendingTransfers = [];
    selectedOutPlayer = null;
    renderTransferHeader();
    renderTransferSquad();
    await loadTransferPlayers();
}

function renderTransferHeader() {
    const header = document.getElementById('transfer-summary');
    if (!header || !currentTeam) return;
    const filled = currentSquad.length;
    const totalValue = currentSquad.reduce((s, sp) => s + (sp.player?.price || 0), 0);
    const ft = currentTeam.free_transfers || 0;
    header.innerHTML = `
        <div class="transfer-summary-grid">
            <div class="ts-cell"><div class="ts-label">Squad</div><div class="ts-value">${filled} / 13</div></div>
            <div class="ts-cell"><div class="ts-label">Bank</div><div class="ts-value">£${(currentTeam.budget_remaining || 0).toFixed(1)}m</div></div>
            <div class="ts-cell"><div class="ts-label">Value</div><div class="ts-value">£${totalValue.toFixed(1)}m</div></div>
            <div class="ts-cell"><div class="ts-label">Free Transfers</div><div class="ts-value">${ft}</div></div>
            <div class="ts-cell"><div class="ts-label">Active Chip</div><div class="ts-value">${chipDisplay(currentTeam.active_chip)}</div></div>
        </div>
        <div class="transfer-actions">
            <button class="btn btn-outline" onclick="autoFillSquad()" ${filled >= 13 ? 'disabled' : ''}>Auto-pick remaining</button>
            <button class="btn btn-outline" onclick="resetTransferSelection()">Reset selection</button>
            <button class="btn btn-warn" onclick="confirmChipActivation('wildcard')" ${currentTeam.active_chip ? 'disabled' : ''}>Play Wildcard</button>
            <button class="btn btn-warn" onclick="confirmChipActivation('free_hit')" ${currentTeam.active_chip ? 'disabled' : ''}>Play Free Hit</button>
        </div>`;
}

function chipDisplay(c) {
    const names = { wildcard: 'Wildcard', free_hit: 'Free Hit', bench_boost: 'Bench Boost', triple_captain: 'Triple Captain' };
    return c ? names[c] || c : '—';
}

function renderTransferSquad() {
    const target = document.getElementById('transfer-selected');
    if (!target) return;
    if (!currentSquad.length) {
        target.innerHTML = '<div class="muted" style="padding:1rem">No players yet — pick from the list below to fill your squad.</div>';
        return;
    }

    const starters = currentSquad.filter(sp => sp.is_starting);
    const bench = currentSquad.filter(sp => !sp.is_starting);

    let html = '<h3>Your squad (' + currentSquad.length + '/13)</h3>';

    html += '<div class="squad-group"><h4>Starting 10</h4><div class="squad-row">';
    for (let i = 0; i < 10; i++) {
        const sp = starters[i];
        if (!sp) {
            html += '<div class="squad-cell empty"><div class="empty-slot">+ player</div></div>';
        } else {
            const isSel = selectedOutPlayer && selectedOutPlayer.id === sp.id;
            html += `
                <div class="squad-cell ${isSel ? 'selected' : ''}" onclick="toggleOutPlayer(${sp.id})">
                    <div class="player-mini">
                        <div class="pm-name">${escapeHtml(sp.player?.name || '')}</div>
                        <div class="pm-team">${escapeHtml(sp.player?.team?.name || '')}</div>
                        <div class="pm-price">&#163;${(sp.player?.price || 0).toFixed(1)}m</div>
                        <button class="btn-x" onclick="event.stopPropagation();dropPlayer(${sp.player_id})" title="Drop">&#215;</button>
                    </div>
                </div>`;
        }
    }
    html += '</div></div>';

    html += '<div class="squad-group"><h4>Bench</h4><div class="squad-row">';
    for (let i = 0; i < 3; i++) {
        const sp = bench[i];
        if (!sp) {
            html += '<div class="squad-cell empty"><div class="empty-slot">+ player</div></div>';
        } else {
            const isSel = selectedOutPlayer && selectedOutPlayer.id === sp.id;
            html += `
                <div class="squad-cell ${isSel ? 'selected' : ''}" onclick="toggleOutPlayer(${sp.id})">
                    <div class="player-mini">
                        <div class="pm-name">${escapeHtml(sp.player?.name || '')}</div>
                        <div class="pm-team">${escapeHtml(sp.player?.team?.name || '')}</div>
                        <div class="pm-price">&#163;${(sp.player?.price || 0).toFixed(1)}m</div>
                        <button class="btn-x" onclick="event.stopPropagation();dropPlayer(${sp.player_id})" title="Drop">&#215;</button>
                    </div>
                </div>`;
        }
    }
    html += '</div></div>';

    target.innerHTML = html;
}

// posLabel removed - no position display

function toggleOutPlayer(squadId) {
    const sp = currentSquad.find(s => s.id === squadId);
    if (!sp) return;
    if (selectedOutPlayer && selectedOutPlayer.id === squadId) {
        selectedOutPlayer = null;
    } else {
        selectedOutPlayer = sp;
    }
    renderTransferSquad();
}

function resetTransferSelection() {
    selectedOutPlayer = null;
    renderTransferSquad();
}

async function loadTransferPlayers() {
    try {
        const r = await apiFetch('/players/?order_by=points');
        if (!r.ok) return;
        transferPlayersCache = await r.json();
        renderTransferList();
    } catch (err) {
        console.error('transfer players', err);
    }
}

function renderTransferList() {
    const container = document.getElementById('transfer-results');
    if (!container) return;
    const search = (document.getElementById('transfer-search-input')?.value || '').toLowerCase();
    const sortKey = document.getElementById('transfer-sort')?.value || 'points';

    const squadIds = new Set(currentSquad.map(sp => sp.player_id));
    let players = transferPlayersCache.slice();
    if (search) players = players.filter(p => (p.name || '').toLowerCase().includes(search));

    const sortMap = {
        points: (a, b) => (b.total_points_season || 0) - (a.total_points_season || 0),
        price_high: (a, b) => b.price - a.price,
        price_low: (a, b) => a.price - b.price,
        form: (a, b) => (b.form || 0) - (a.form || 0),
        selected: (a, b) => (b.selected_by_percent || 0) - (a.selected_by_percent || 0),
    };
    players.sort(sortMap[sortKey] || sortMap.points);

    container.innerHTML = `
        <div class="transfer-list-header">
            <div>Player</div><div>Team</div>
            <div>£</div><div>Pts</div><div>Form</div><div>%</div><div></div>
        </div>
        <div class="transfer-list">
            ${players.slice(0, 100).map(p => {
                const inSquad = squadIds.has(p.id);
                const action = inSquad
                    ? `<button class="btn btn-sm btn-outline" onclick="dropPlayer(${p.id})">Drop</button>`
                    : selectedOutPlayer
                        ? `<button class="btn btn-sm btn-primary" onclick="swapPlayer(${p.id})">Swap In</button>`
                        : currentSquad.length < 13
                            ? `<button class="btn btn-sm btn-secondary" onclick="addPlayer(${p.id})">Add</button>`
                            : '';
                return `
                    <div class="transfer-row ${inSquad ? 'in-squad' : ''}">
                        <div class="t-name">${escapeHtml(p.name)}${p.is_injured ? ' <span class="injury-dot">!</span>' : ''}</div>
                        <div>${escapeHtml(p.team?.name || '')}</div>
                        <div>£${p.price.toFixed(1)}m</div>
                        <div>${p.total_points_season || 0}</div>
                        <div>${(p.form || 0).toFixed(1)}</div>
                        <div>${(p.selected_by_percent || 0).toFixed(1)}%</div>
                        <div>${action}</div>
                    </div>`;
            }).join('')}
        </div>`;
}

function searchTransferPlayers() { renderTransferList(); }

async function addPlayer(playerId) {
    if (!currentTeam) return;
    const r = await apiFetch('/transfers/player', {
        method: 'POST',
        body: JSON.stringify({ fantasy_team_id: currentTeam.id, player_in_id: playerId }),
    });
    const data = await r.json();
    if (r.ok) {
        showToast(`Added ${data.player_in?.name || 'player'}`, 'success');
        await loadTeam();
        renderTransferHeader();
        renderTransferSquad();
        renderTransferList();
    } else {
        showToast(data.detail || 'Failed', 'error');
    }
}

async function dropPlayer(playerId) {
    if (!currentTeam) return;
    if (!confirm('Drop this player from your squad?')) return;
    const r = await apiFetch('/transfers/player', {
        method: 'POST',
        body: JSON.stringify({ fantasy_team_id: currentTeam.id, player_out_id: playerId }),
    });
    const data = await r.json();
    if (r.ok) {
        showToast(`Dropped ${data.player_out?.name || 'player'} (£${data.player_out?.sold_for}m back)`, 'success');
        selectedOutPlayer = null;
        await loadTeam();
        renderTransferHeader();
        renderTransferSquad();
        renderTransferList();
    } else {
        showToast(data.detail || 'Failed', 'error');
    }
}

async function swapPlayer(playerInId) {
    if (!currentTeam || !selectedOutPlayer) return;
    const r = await apiFetch('/transfers/player', {
        method: 'POST',
        body: JSON.stringify({
            fantasy_team_id: currentTeam.id,
            player_in_id: playerInId,
            player_out_id: selectedOutPlayer.player_id,
        }),
    });
    const data = await r.json();
    if (r.ok) {
        const hit = data.points_hit ? ` (-${data.points_hit} pts)` : '';
        showToast(`Swapped to ${data.player_in?.name}${hit}`, 'success');
        selectedOutPlayer = null;
        await loadTeam();
        renderTransferHeader();
        renderTransferSquad();
        renderTransferList();
    } else {
        showToast(data.detail || 'Failed', 'error');
    }
}

async function autoFillSquad() {
    if (!currentTeam) return;

    // Pick cheapest 13 players not already in squad (no position limits)
    const candidates = transferPlayersCache
        .filter(p => !currentSquad.some(s => s.player_id === p.id))
        .sort((a, b) => a.price - b.price);

    const need = 13 - currentSquad.length;
    for (let i = 0; i < need; i++) {
        const p = candidates[i];
        if (!p) break;
        const r = await apiFetch('/transfers/player', {
            method: 'POST',
            body: JSON.stringify({ fantasy_team_id: currentTeam.id, player_in_id: p.id }),
        });
        if (!r.ok) {
            const err = await r.json();
            showToast(`Stopped: ${err.detail || 'failed'}`, 'error');
            break;
        }
    }
    showToast('Auto-pick complete', 'success');
    await loadTeam();
    renderTransferHeader();
    renderTransferSquad();
    renderTransferList();
}

// ===== PLAYERS PAGE =====
async function loadPlayers() {
    const search = document.getElementById('player-search')?.value || '';
    const sort = document.getElementById('player-sort')?.value || 'points';
    let url = `/players/?order_by=${sort}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    try {
        const r = await apiFetch(url);
        if (!r.ok) return;
        const players = await r.json();
        renderPlayers(players);
    } catch (err) { console.error('players', err); }
}

function renderPlayers(players) {
    const container = document.getElementById('players-container');
    if (!container) return;
    container.innerHTML = `
        <div class="players-table">
            <table>
                <thead>
                    <tr>
                        <th>Name</th><th>Team</th>
                        <th>Price</th><th>Pts</th><th>Goals</th><th>Assists</th><th>CS</th>
                        <th>Form</th><th>%Sel</th>
                    </tr>
                </thead>
                <tbody>
                    ${players.map(p => `
                        <tr onclick="showPlayerDetail(${p.id})">
                            <td class="player-name">${escapeHtml(p.name)}</td>
                            <td>${escapeHtml(p.team?.name || '')}</td>
                            <td>£${p.price.toFixed(1)}m</td>
                            <td>${p.total_points_season || 0}</td>
                            <td>${p.goals || 0}</td>
                            <td>${p.assists || 0}</td>
                            <td>${p.clean_sheets || 0}</td>
                            <td>${(p.form || 0).toFixed(1)}</td>
                            <td>${(p.selected_by_percent || 0).toFixed(1)}%</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
}

// ===== FIXTURES =====
async function loadFixtures() {
    const gwSelect = document.getElementById('fixtures-gw-select')?.value || '';
    let url = '/fixtures/';
    if (gwSelect) url += `?gameweek_id=${gwSelect}`;
    try {
        const r = await apiFetch(url);
        if (!r.ok) return;
        const data = await r.json();
        renderFixtures(data.fixtures);
        loadGameweekOptions();
        loadTeamFilterOptions();
    } catch (err) { console.error('fixtures', err); }
}

function renderFixtures(fixtures) {
    const container = document.getElementById('fixtures-container');
    if (!container) return;
    if (!fixtures || !fixtures.length) {
        container.innerHTML = '<div class="empty-state">No fixtures available</div>';
        return;
    }
    const byGW = {};
    fixtures.forEach(f => {
        const gw = f.gameweek_id;
        if (!byGW[gw]) byGW[gw] = [];
        byGW[gw].push(f);
    });
    let html = '';
    Object.keys(byGW).sort((a, b) => a - b).forEach(gwId => {
        const list = byGW[gwId];
        html += `<div class="fixture-gw"><h3>Gameweek ${gwId}</h3><div class="fixture-list">`;
        list.forEach(f => {
            const homeDiff = getDifficultyClass(f.home_difficulty);
            const awayDiff = getDifficultyClass(f.away_difficulty);
            html += `
                <div class="fixture-row">
                    <div class="fixture-team home">
                        <span class="team-name">${escapeHtml(f.home_team)}</span>
                        <span class="difficulty-badge ${homeDiff}">${f.home_difficulty}</span>
                    </div>
                    <div class="fixture-result">
                        ${f.played ? `<span class="score">${f.home_score}-${f.away_score}</span>` : `<span class="vs">vs</span>`}
                        ${f.date ? `<span class="fixture-date">${formatDate(f.date)} ${formatTime(f.date)}</span>` : ''}
                    </div>
                    <div class="fixture-team away">
                        <span class="difficulty-badge ${awayDiff}">${f.away_difficulty}</span>
                        <span class="team-name">${escapeHtml(f.away_team)}</span>
                    </div>
                </div>`;
        });
        html += '</div></div>';
    });
    container.innerHTML = html;
}

function getDifficultyClass(d) {
    if (d >= 5) return 'hh';
    if (d >= 4) return 'h';
    if (d >= 3) return 'm';
    if (d >= 2) return 'e';
    return 'ee';
}

async function loadGameweekOptions() {
    const select = document.getElementById('fixtures-gw-select');
    if (!select) return;
    try {
        const r = await apiFetch('/gameweeks/');
        if (!r.ok) return;
        const data = await r.json();
        const gameweeks = data.gameweeks || [];
        const cur = select.value;
        select.innerHTML = '<option value="">All Gameweeks</option>'
            + gameweeks.map(gw => `<option value="${gw.id}">GW ${gw.number}</option>`).join('');
        select.value = cur;
    } catch (e) { console.error(e); }
}
async function loadTeamFilterOptions() {
    const select = document.getElementById('fixtures-team-filter');
    if (!select) return;
    try {
        const r = await apiFetch('/teams/');
        if (!r.ok) return;
        const data = await r.json();
        const teams = data.teams || [];
        const cur = select.value;
        select.innerHTML = '<option value="">All Teams</option>'
            + teams.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');
        select.value = cur;
    } catch (e) { console.error(e); }
}

// ===== GAMEWEEKS =====
async function loadGameweeks() {
    try {
        const r = await apiFetch('/gameweeks/');
        if (!r.ok) return;
        const data = await r.json();
        allGameweeks = data.gameweeks || [];
        renderGameweeks(data);
    } catch (err) { console.error('gameweeks', err); }
}

function renderGameweeks(data) {
    const container = document.getElementById('gameweeks-container');
    if (!container) return;
    const list = data.gameweeks || [];
    if (!list.length) {
        container.innerHTML = '<div class="empty-state">No gameweeks configured.</div>';
        return;
    }
    const cur = data.current_gw;
    let html = '';
    if (cur) {
        html += `
            <div class="current-gw-card">
                <div>
                    <div class="cgw-label">Current Gameweek</div>
                    <h3>Gameweek ${cur.number}</h3>
                    <p>Deadline: ${formatDateTime(cur.deadline)}</p>
                </div>
                <div class="cgw-countdown" id="cgw-countdown" data-deadline="${cur.deadline}">
                    ${cur.deadline ? formatCountdown(Math.max(0, Math.floor((new Date(cur.deadline).getTime() - Date.now()) / 1000))) : '—'}
                </div>
            </div>`;
    }
    html += '<div class="gw-grid">';
    list.forEach(gw => {
        const klass = [
            gw.is_current ? 'current' : '',
            gw.scored ? 'scored' : '',
            gw.closed ? 'closed' : 'open',
        ].filter(Boolean).join(' ');
        html += `
            <div class="gw-card ${klass}" onclick="loadGameweekDetails(${gw.id})">
                <div class="gw-card-header">
                    <h4>GW ${gw.number}</h4>
                    ${gw.is_current ? '<span class="badge badge-current">Current</span>' : ''}
                </div>
                <div class="gw-card-body">
                    <div class="gw-deadline">${gw.deadline ? formatDate(gw.deadline) : ''}</div>
                    <div class="gw-meta">${gw.fixture_count || 0} fixtures</div>
                    <div class="gw-status">
                        ${gw.scored ? '<span class="badge badge-scored">Scored</span>'
                            : gw.closed ? '<span class="badge badge-closed">Closed</span>'
                            : '<span class="badge badge-open">Open</span>'}
                    </div>
                </div>
            </div>`;
    });
    html += '</div>';
    html += '<div id="gameweek-detail-pane"></div>';
    container.innerHTML = html;

    // Live countdown for current GW card
    const cd = document.getElementById('cgw-countdown');
    if (cd) {
        const deadline = cd.dataset.deadline;
        if (deadline) {
            const t = Math.floor(new Date(deadline).getTime() / 1000);
            startGwCountdown(cd, t);
        }
    }
    // Auto-load current GW details
    if (cur) loadGameweekDetails(cur.id);
}

function startGwCountdown(el, deadlineUnix) {
    const update = () => {
        const remaining = deadlineUnix - Math.floor(Date.now() / 1000);
        if (remaining <= 0) { el.textContent = 'Deadline passed'; return; }
        el.textContent = formatCountdown(remaining);
    };
    update();
    setInterval(update, 1000);
}

async function loadGameweekDetails(gwId) {
    const pane = document.getElementById('gameweek-detail-pane');
    if (!pane) return;
    pane.innerHTML = '<div class="muted" style="padding:1rem">Loading…</div>';
    try {
        const [statsResp, fxResp] = await Promise.all([
            apiFetch(`/stats/gameweek/${gwId}`),
            apiFetch(`/fixtures/?gameweek_id=${gwId}`),
        ]);
        const stats = statsResp.ok ? await statsResp.json() : {};
        const fxData = fxResp.ok ? await fxResp.json() : { fixtures: [] };
        const fixtures = fxData.fixtures || [];

        pane.innerHTML = `
            <div class="gw-detail-card">
                <div class="gw-detail-header">
                    <h3>Gameweek ${stats.gameweek_number} details</h3>
                    <div class="gw-detail-stats">
                        <div><span class="muted">Average</span> <strong>${stats.average_score ?? '—'}</strong></div>
                        <div><span class="muted">Highest</span> <strong>${stats.highest_score ?? '—'}</strong></div>
                        <div><span class="muted">Managers</span> <strong>${stats.managers_played ?? 0}</strong></div>
                    </div>
                </div>
                <div class="gw-detail-grid">
                    <div>
                        <h4>Fixtures</h4>
                        <div class="fixture-list">
                            ${fixtures.length ? fixtures.map(f => `
                                <div class="fixture-row">
                                    <div class="fixture-team home"><span class="team-name">${escapeHtml(f.home_team)}</span></div>
                                    <div class="fixture-result">
                                        ${f.played ? `<span class="score">${f.home_score}-${f.away_score}</span>` : `<span class="vs">vs</span>`}
                                        ${f.date ? `<span class="fixture-date">${formatDate(f.date)} ${formatTime(f.date)}</span>` : ''}
                                    </div>
                                    <div class="fixture-team away"><span class="team-name">${escapeHtml(f.away_team)}</span></div>
                                </div>`).join('') : '<div class="muted">No fixtures</div>'}
                        </div>
                    </div>
                    <div>
                        <h4>Top performers</h4>
                        <div class="top-performers">
                            ${(stats.top_players || []).map(p => `
                                <div class="top-perf-row">
                                    <span class="tp-name">${escapeHtml(p.name)}</span>
                                    <span class="muted">${escapeHtml(p.team_name)}</span>
                                    <span class="tp-points">${p.points} pts</span>
                                </div>`).join('') || '<div class="muted">No stats yet</div>'}
                        </div>
                    </div>
                </div>
            </div>`;
    } catch (err) {
        console.error('gw details', err);
        pane.innerHTML = '<div class="error-state">Failed to load gameweek details</div>';
    }
}

async function syncGameweeks() {
    try {
        const r = await apiFetch('/gameweeks/sync', { method: 'POST' });
        if (r.ok) {
            showToast('Fixtures synced', 'success');
            await loadGameweeks();
        } else {
            const err = await r.json();
            showToast(err.detail || 'Failed', 'error');
        }
    } catch (err) {
        showToast('Sync failed: ' + err.message, 'error');
    }
}

// ===== HISTORY =====
async function loadHistoryPage() {
    if (!currentUser) return navigate('login');
    if (!currentTeam) await loadTeam();
    await loadHistorySummary();
    await loadGameweekOptionsForHistory();
    await loadTransferHistory();
    // Auto-pick latest gameweek with breakdown if available
    const sel = document.getElementById('history-gw-select');
    if (sel && sel.options.length > 1) {
        sel.selectedIndex = 1;
        loadGameweekBreakdown();
    }
}

async function loadHistorySummary() {
    const container = document.getElementById('history-summary');
    if (!container || !currentTeam) return;
    try {
        const r = await apiFetch(`/leaderboard/${currentTeam.user_id}/history`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.history || !data.history.length) {
            container.innerHTML = '<div class="empty-state">No history yet — wait for gameweeks to be scored.</div>';
            return;
        }
        const entries = data.history;
        const total = entries.length;
        const sumPoints = entries.reduce((s, h) => s + h.points, 0);
        const avg = (sumPoints / total).toFixed(1);
        const best = Math.max(...entries.map(h => h.points));
        const worst = Math.min(...entries.map(h => h.points));
        const totalPoints = entries[entries.length - 1]?.total_points || 0;
        const totalCost = entries.reduce((s, h) => s + (h.transfers_cost || 0), 0);

        container.innerHTML = `
            <div class="history-stats-grid">
                <div class="history-stat-card"><div class="stat-value">${totalPoints}</div><div class="stat-label">Total Points</div></div>
                <div class="history-stat-card"><div class="stat-value">${avg}</div><div class="stat-label">Avg/GW</div></div>
                <div class="history-stat-card"><div class="stat-value">${best}</div><div class="stat-label">Best GW</div></div>
                <div class="history-stat-card"><div class="stat-value">${worst}</div><div class="stat-label">Worst GW</div></div>
                <div class="history-stat-card"><div class="stat-value">-${totalCost}</div><div class="stat-label">Hits Taken</div></div>
            </div>
            <div class="history-table-wrap">
                <table class="history-table">
                    <thead>
                        <tr><th>GW</th><th>Pts</th><th>Avg</th><th>Total</th><th>Rank</th><th>Trs</th><th>Cost</th><th>Chip</th></tr>
                    </thead>
                    <tbody>
                        ${entries.map(h => `
                            <tr>
                                <td>${h.gameweek}</td>
                                <td><strong>${h.points}</strong></td>
                                <td class="muted">—</td>
                                <td>${h.total_points}</td>
                                <td>${h.rank || '—'}</td>
                                <td>${h.transfers_made || 0}</td>
                                <td>${h.transfers_cost ? '-' + h.transfers_cost : 0}</td>
                                <td>${h.chip_used ? `<span class="chip-badge chip-${h.chip_used}">${chipDisplay(h.chip_used)}</span>` : ''}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
    } catch (err) { console.error('history summary', err); }
}

async function loadGameweekOptionsForHistory() {
    const select = document.getElementById('history-gw-select');
    if (!select) return;
    try {
        const r = await apiFetch('/gameweeks/');
        if (!r.ok) return;
        const data = await r.json();
        const list = data.gameweeks || [];
        select.innerHTML = '<option value="">Select Gameweek</option>'
            + list.filter(gw => gw.scored || gw.closed)
                  .map(gw => `<option value="${gw.id}">GW ${gw.number}</option>`).join('');
    } catch (e) { console.error(e); }
}

async function loadGameweekBreakdown() {
    const select = document.getElementById('history-gw-select');
    const breakdown = document.getElementById('history-breakdown');
    if (!select || !breakdown || !currentTeam) return;
    const gwId = select.value;
    if (!gwId) {
        breakdown.innerHTML = '<div class="empty-state">Select a gameweek to see your detailed breakdown.</div>';
        return;
    }
    try {
        const r = await apiFetch(`/gameweek-history/${currentTeam.id}/${gwId}`);
        if (!r.ok) {
            breakdown.innerHTML = '<div class="empty-state">No breakdown available for this gameweek yet.</div>';
            return;
        }
        const data = await r.json();
        breakdown.innerHTML = `
            <div class="gw-breakdown-header">
                <h3>GW ${data.gameweek} breakdown</h3>
                <div class="breakdown-stats">
                    <span><strong>${data.total_points}</strong> pts</span>
                    <span class="muted">XI: ${data.starting_points}</span>
                    <span class="muted">Bench: ${data.bench_points}</span>
                    ${data.transfers_cost ? `<span class="cost">-${data.transfers_cost} hits</span>` : ''}
                    ${data.chip_used ? `<span class="chip-badge chip-${data.chip_used}">${chipDisplay(data.chip_used)}</span>` : ''}
                </div>
            </div>
            <div class="player-breakdown-grid">
                ${(data.player_breakdown || []).map(p => `
                    <div class="player-breakdown-card ${p.is_starting ? 'starting' : 'bench'}">
                        <div class="pb-header">
                            <span class="pb-name">${escapeHtml(p.name)}</span>
                            ${p.is_captain ? '<span class="captain-badge-sm">C</span>' : ''}
                            ${p.is_vice_captain ? '<span class="vice-badge-sm">V</span>' : ''}
                            ${p.was_autosub ? '<span class="autosub-badge">AS</span>' : ''}
                        </div>
                        <div class="pb-meta muted">${escapeHtml(p.team_name || '')}</div>
                        <div class="pb-stats">
                            <span>${p.minutes || 0}'</span>
                            ${p.goals ? `<span>${p.goals}G</span>` : ''}
                            ${p.assists ? `<span>${p.assists}A</span>` : ''}
                            ${p.clean_sheets ? '<span>CS</span>' : ''}
                            ${p.bonus ? `<span>+${p.bonus}B</span>` : ''}
                        </div>
                        <div class="pb-points ${p.points > 0 ? 'positive' : ''}">${p.points} pts</div>
                    </div>`).join('')}
            </div>`;
    } catch (err) {
        console.error('breakdown', err);
        breakdown.innerHTML = '<div class="error-state">Failed to load breakdown</div>';
    }
}

async function loadTransferHistory() {
    const container = document.getElementById('transfer-history-container');
    if (!container || !currentTeam) return;
    try {
        const r = await apiFetch(`/gameweek-history/transfer-history/${currentTeam.id}`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.transfers || !data.transfers.length) {
            container.innerHTML = '<div class="empty-state">No transfers yet</div>';
            return;
        }
        container.innerHTML = data.transfers.map(t => `
            <div class="transfer-history-row">
                <span class="transfer-gw">GW ${t.gameweek || '?'}</span>
                <span class="transfer-in">+ ${escapeHtml(t.player_in?.name || '?')}</span>
                ${t.player_out
                    ? `<span class="transfer-out">- ${escapeHtml(t.player_out.name)} (${t.player_out.points_scored || 0} pts)</span>`
                    : ''}
                ${t.is_wildcard ? '<span class="badge badge-wildcard">WC</span>' : ''}
                ${t.is_free_hit ? '<span class="badge badge-freehit">FH</span>' : ''}
            </div>`).join('');
    } catch (err) { console.error('th', err); }
}

// ===== LEADERBOARD =====
async function loadLeaderboard() {
    try {
        const r = await apiFetch('/leaderboard/?limit=100');
        if (!r.ok) return;
        const data = await r.json();
        renderLeaderboard(data);
        if (currentUser) loadUserRank();
    } catch (err) { console.error('leaderboard', err); }
}

function renderLeaderboard(data) {
    const container = document.getElementById('leaderboard-container');
    if (!container) return;
    const stats = document.getElementById('leaderboard-stats');
    if (stats) stats.innerHTML = `<span>Total Teams: ${data.total_teams}</span>`;
    container.innerHTML = `
        <div class="leaderboard-table">
            <table>
                <thead><tr><th>Rank</th><th>Manager</th><th>Team</th><th>GW</th><th>Total</th></tr></thead>
                <tbody>
                    ${(data.entries || []).map(e => `
                        <tr>
                            <td>${e.rank}</td>
                            <td>${escapeHtml(e.username)}</td>
                            <td>${escapeHtml(e.team_name)}</td>
                            <td>${e.gameweek_points ?? '—'}</td>
                            <td class="points">${e.total_points}</td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>`;
}

async function loadUserRank() {
    const stats = document.getElementById('leaderboard-stats');
    if (!stats || !currentTeam) return;
    try {
        const r = await apiFetch(`/leaderboard/${currentTeam.user_id}/rank`);
        if (!r.ok) return;
        const data = await r.json();
        stats.innerHTML = `
            <span>Total Teams: ${data.total_teams}</span>
            <span>Your Rank: #${data.rank}</span>
            <span>Percentile: ${data.percentile}%</span>
            ${data.rank_change != null ? `<span class="rank-change ${data.rank_change > 0 ? 'up' : data.rank_change < 0 ? 'down' : ''}">${data.rank_change > 0 ? '↑' : data.rank_change < 0 ? '↓' : '='} ${Math.abs(data.rank_change)}</span>` : ''}`;
    } catch (e) { console.error(e); }
}

// ===== DREAM TEAM =====
async function loadDreamTeamPage() {
    const select = document.getElementById('dream-team-gw-select');
    if (!select) return;
    try {
        const r = await apiFetch('/gameweeks/');
        if (!r.ok) return;
        const data = await r.json();
        const list = data.gameweeks || [];
        // Prefer scored/closed GWs
        const eligible = list.filter(gw => gw.scored || gw.closed);
        const cur = select.value;
        select.innerHTML = '<option value="">Select Gameweek</option>'
            + eligible.map(gw => `<option value="${gw.id}">GW ${gw.number}</option>`).join('');
        if (eligible.length) {
            select.value = cur || eligible[eligible.length - 1].id;
            loadDreamTeam();
        } else {
            document.getElementById('dream-team-players').innerHTML =
                '<div class="empty-state">Dream Team becomes available once gameweeks have been scored.</div>';
        }
    } catch (e) { console.error(e); }
}

async function loadDreamTeam() {
    const select = document.getElementById('dream-team-gw-select');
    const container = document.getElementById('dream-team-players');
    const totalDiv = document.getElementById('dream-team-total');
    if (!select || !container) return;
    const gwId = select.value;
    if (!gwId) { container.innerHTML = '<div class="empty-state">Select a gameweek</div>'; return; }
    try {
        const r = await apiFetch(`/dream-team/${gwId}`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.players || !data.players.length) {
            container.innerHTML = `<div class="empty-state">${data.message || 'Dream team not yet available'}</div>`;
            if (totalDiv) totalDiv.innerHTML = '';
            return;
        }

        let html = '';
        // Simple 2-3-2-3 layout for 10 players (no GK)
        const rows = [
            { players: data.players.slice(0, 2), top: 20 },
            { players: data.players.slice(2, 5), top: 40 },
            { players: data.players.slice(5, 7), top: 60 },
            { players: data.players.slice(7, 10), top: 80 },
        ];
        for (const row of rows) {
            html += renderDreamRow(row.players, row.top);
        }
        container.innerHTML = html;

        if (totalDiv) {
            totalDiv.innerHTML = `
                <div class="dream-total-card">
                    <div><span class="muted">Combined Total</span> <strong>${data.total_points} pts</strong></div>
                    <div><span class="muted">Players</span> <strong>${data.players.length}</strong></div>
                </div>`;
        }
    } catch (err) { console.error('dream team', err); }
}

function renderDreamRow(players, top) {
    if (!players.length) return '';
    return `<div class="pitch-row" style="top:${top}%">${players.map((p, i) => {
        const x = (100 / (players.length + 1)) * (i + 1);
        const captain = p.is_captain ? '<div class="captain-badge">C</div>' : '';
        const teamName = p.team_name || '';
        const gradient = shirtGradient(teamName);
        const gradientLight = shirtGradientLight(teamName);
        return `
            <div class="pitch-slot" style="left:${x}%">
                <div class="player-card fpl-card" style="--shirt-dark:${gradient};--shirt-light:${gradientLight}">
                    ${captain}
                    <div class="fpl-shirt" style="background-image:url(${shirtIcon(teamName)})"></div>
                    <div class="fpl-player-name">${escapeHtml(p.name)}</div>
                    <div class="fpl-player-team">${escapeHtml(teamName)}</div>
                    <div class="fpl-player-points">${p.points} pts</div>
                </div>
            </div>`;
    }).join('')}</div>`;
}

// ===== LEAGUES =====
async function loadLeagues() {
    if (!currentUser) return navigate('login');
    const container = document.getElementById('leagues-container');
    if (!container) return;
    try {
        const r = await apiFetch('/mini_leagues/');
        if (!r.ok) return;
        const data = await r.json();
        if (!data.leagues || !data.leagues.length) {
            container.innerHTML = '<div class="empty-state">No leagues yet — create or join one.</div>';
            return;
        }
        container.innerHTML = data.leagues.map(l => `
            <div class="league-card">
                <div class="league-header"><h3>${escapeHtml(l.name)}</h3><span class="league-code">${l.code}</span></div>
                <p class="muted">Members: ${l.members?.length || 0}</p>
                <div class="league-standings">
                    ${(l.standings || []).map(s => `
                        <div class="standings-row">
                            <span class="rank">#${s.rank}</span>
                            <span>${escapeHtml(s.team_name)}</span>
                            <span class="points">${s.total_points} pts</span>
                        </div>`).join('')}
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}

function showCreateLeague() {
    const name = prompt('League name:');
    if (!name) return;
    apiFetch('/mini_leagues/', {
        method: 'POST',
        body: JSON.stringify({ name, is_h2h: false }),
    }).then(r => r.json()).then(data => {
        showToast(`League created (code: ${data.code || data.invite_code || ''})`, 'success');
        loadLeagues();
    });
}
function showJoinLeague() {
    const code = prompt('Enter league code:');
    if (!code) return;
    apiFetch(`/mini_leagues/${code}/join`, { method: 'POST' }).then(() => {
        showToast('Joined league', 'success');
        loadLeagues();
    });
}

// ===== NOTIFICATIONS =====
async function loadNotifications() {
    if (!currentTeam) return;
    const container = document.getElementById('notifications-container');
    if (!container) return;
    try {
        const r = await apiFetch(`/notifications/team/${currentTeam.id}`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.notifications || !data.notifications.length) {
            container.innerHTML = '<p class="empty-state">No notifications yet.</p>';
            return;
        }
        container.innerHTML = data.notifications.map(n => `
            <div class="notification-item ${n.read ? 'read' : 'unread'}">
                <div class="notification-content">
                    <div class="notification-title">${escapeHtml(n.title || '')}</div>
                    <div class="notification-message">${escapeHtml(n.message || '')}</div>
                    <div class="notification-time">${n.timestamp ? formatDateTime(n.timestamp) : ''}</div>
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}
async function markAllNotificationsRead() {
    if (!currentTeam) return;
    await apiFetch(`/notifications/team/${currentTeam.id}/mark-all-read`, { method: 'POST' });
    showToast('All notifications marked as read', 'success');
    loadNotifications();
}

// ===== PLAYER DETAIL =====
async function showPlayerDetail(playerId) {
    try {
        const r = await apiFetch(`/players/${playerId}/detail`);
        if (!r.ok) return;
        const data = await r.json();
        renderPlayerDetailModal(data);
    } catch (e) { console.error(e); }
}
function renderPlayerDetailModal(data) {
    const { player, form_guide, gw_history, upcoming_fixtures } = data;
    const overlay = document.getElementById('modal-overlay');
    const content = document.getElementById('modal-content');
    content.style.maxWidth = '640px';
    content.style.display = 'block';
    content.innerHTML = `
        <div class="player-detail-modal">
            <div class="player-detail-header">
                <div>
                  <h2>${escapeHtml(player.name)}</h2>
                    <div class="muted">
                        ${escapeHtml(player.team_name || '')}
                    </div>
                </div>
                <div class="player-detail-price">
                    <div class="price-main">£${player.price.toFixed(1)}m</div>
                    <div class="muted">${(player.selected_by_percent || 0).toFixed(1)}% selected</div>
                </div>
            </div>
            <div class="stat-grid">
                <div class="stat-item"><div class="stat-label">Total Points</div><div class="stat-value">${player.total_points || 0}</div></div>
                <div class="stat-item"><div class="stat-label">Form</div><div class="stat-value">${(player.form || 0).toFixed(1)}</div></div>
                <div class="stat-item"><div class="stat-label">Goals</div><div class="stat-value">${player.goals || 0}</div></div>
                <div class="stat-item"><div class="stat-label">Assists</div><div class="stat-value">${player.assists || 0}</div></div>
                <div class="stat-item"><div class="stat-label">Clean Sheets</div><div class="stat-value">${player.clean_sheets || 0}</div></div>
                <div class="stat-item"><div class="stat-label">Bonus</div><div class="stat-value">${player.bonus || 0}</div></div>
            </div>
            ${form_guide && form_guide.length ? `
                <h4>Recent Form</h4>
                <div class="form-guide">
                    ${form_guide.map(f => {
                        const cls = f.points >= 10 ? 'high' : f.points >= 5 ? 'mid' : 'low';
                        return `<span class="form-pill form-${cls}" title="GW${f.gameweek}">${f.points}</span>`;
                    }).join('')}
                </div>` : ''}
            ${upcoming_fixtures && upcoming_fixtures.length ? `
                <h4>Upcoming</h4>
                <div class="upcoming-fixtures">
                    ${upcoming_fixtures.map(f => `<span class="fix-pill diff-${f.difficulty}">${f.is_home ? '(H)' : '(A)'} ${escapeHtml(f.opponent || '')}</span>`).join('')}
                </div>` : ''}
            <button class="btn btn-secondary btn-block" onclick="closeModal()" style="margin-top:1rem">Close</button>
        </div>`;
    overlay.style.display = 'block';
}

// ===== TOAST =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ===== UTILS =====
function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}
function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function formatTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

// Real IOM Premier League club kit SVG icons (source: Wikipedia)
const CLUB_COLORS = {
    'Ayre United':       { svg: '/static/img/shirts/Ayre-United.svg', base: '#FF8C00', accent: '#FF8C00' },
    'Braddan':           { svg: '/static/img/shirts/Braddan.svg', base: '#1B3A8C', accent: '#1B3A8C' },
    'Corinthians':       { svg: '/static/img/shirts/Corinthians.svg', base: '#FFFFFF', accent: '#FFFFFF' },
    'DHSOB':             { svg: '/static/img/shirts/DHSOB.svg', base: '#1B3580', accent: '#FFFFFF' },
    'Foxdale':           { svg: '/static/img/shirts/Foxdale.svg', base: '#1B4090', accent: '#FFFFFF' },
    'Laxey':             { svg: '/static/img/shirts/Laxey.svg', base: '#006400', accent: '#FFFFFF' },
    'Onchan':            { svg: '/static/img/shirts/Onchan.svg', base: '#FFD700', accent: '#1B3580' },
    'Peel':              { svg: '/static/img/shirts/Peel.svg', base: '#C41E1E', accent: '#FFFFFF' },
    'Ramsey':            { svg: '/static/img/shirts/Ramsey.svg', base: '#1B3A8C', accent: '#FFFFFF' },
    'Rushen United':     { svg: '/static/img/shirts/Rushen-United.svg', base: '#FFD700', accent: '#1a1a1a' },
    'St Johns':          { svg: '/static/img/shirts/St-Johns.svg', base: '#1B3A8C', accent: '#FFD700' },
    'St Johns United':   { svg: '/static/img/shirts/St-Johns-United.svg', base: '#1B3A8C', accent: '#FFD700' },
    'St Marys':          { svg: '/static/img/shirts/St-Marys.svg', base: '#1A7A1A', accent: '#FFD700' },
    'Union Mills':       { svg: '/static/img/shirts/Union-Mills.svg', base: '#800020', accent: '#87CEEB' },
    'Marown':            { svg: '/static/img/shirts/Marown.svg', base: '#1B3A8C', accent: '#FFFFFF' },
};

// Get SVG shirt icon path for a team
function shirtIcon(name) {
    const c = CLUB_COLORS[name];
    return c ? c.svg : '/static/img/shirts/default.svg';
}

// Fallback: get base color for a team (used for backgrounds, etc.)
function shirtGradient(name) {
    const c = CLUB_COLORS[name];
    return c ? c.base : '#555555';
}
function shirtGradientLight(name) {
    const c = CLUB_COLORS[name];
    return c ? c.accent : '#888888';
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
    updateNav();
    if (getToken()) {
        loadTeam().then(() => {
            if (currentTeam) navigate('my-team');
            else navigate('home');
        });
    } else {
        loadHomePage();
    }
});
