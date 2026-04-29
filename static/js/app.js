/**
 * Fantasy Football Isle of Man - Main Application JavaScript
 * FPL-style fantasy football for Isle of Man leagues
 */

// ===== CONFIG =====
const API_BASE = '/api';
let currentUser = null;
let currentTeam = null;
let countdownInterval = null;

// ===== AUTH =====
async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
        const response = await fetch(`${API_BASE}/users/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('token', data.access_token);
            currentUser = data.user;
            loadTeam();
            updateNav();
            navigate('my-team');
        } else {
            const err = await response.json();
            showToast(err.detail || 'Login failed', 'error');
        }
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
            body: JSON.stringify({ username, email, password, team_name: teamName })
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('token', data.access_token);
            currentUser = data.user;
            loadTeam();
            updateNav();
            navigate('my-team');
            showToast('Account created!', 'success');
        } else {
            const err = await response.json();
            showToast(err.detail || 'Registration failed', 'error');
        }
    } catch (err) {
        showToast('Registration failed: ' + err.message, 'error');
    }
}

function logout() {
    localStorage.removeItem('token');
    currentUser = null;
    currentTeam = null;
    updateNav();
    navigate('home');
}

function getToken() {
    return localStorage.getItem('token');
}

async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}${url}`, { ...options, headers });
    if (response.status === 401) {
        logout();
        throw new Error('Unauthorized');
    }
    return response;
}

// ===== NAVIGATION =====
function navigate(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    const navLink = document.querySelector(`.nav-link[data-page="${page}"]`);
    if (navLink) navLink.classList.add('active');

    // Load page data
    switch (page) {
        case 'home': loadHomePage(); break;
        case 'my-team': loadMyTeam(); break;
        case 'players': loadPlayers(); break;
        case 'fixtures': loadFixtures(); break;
        case 'gameweeks': loadGameweeks(); break;
        case 'history': loadHistoryPage(); break;
        case 'leaderboard': loadLeaderboard(); break;
        case 'dream-team': loadDreamTeamPage(); break;
        case 'leagues': loadLeagues(); break;
        case 'transfers': loadTransfersPage(); break;
        case 'notifications': loadNotifications(); break;
        case 'recap': loadGWRecap(); break;
        case 'h2h': loadH2HPage(); break;
    }
}

function updateNav() {
    const authDiv = document.getElementById('nav-auth');
    if (currentUser) {
        authDiv.innerHTML = `
            <span class="nav-user">${currentUser.username}</span>
            <button class="btn btn-sm btn-outline" onclick="logout()">Logout</button>
        `;
    } else {
        authDiv.innerHTML = `
            <button class="btn btn-sm btn-primary" onclick="navigate('login')">Login</button>
        `;
    }
}

// ===== HOME PAGE =====
async function loadHomePage() {
    await loadGameweekBanner();
}

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
                    <p class="gw-deadline">Deadline: ${new Date(data.deadline).toLocaleString()}</p>
                    ${data.is_closed ? '<span class="badge badge-closed">Closed</span>' : ''}
                </div>
                <div class="gw-banner-right">
                    <div class="gw-countdown" id="gw-countdown">
                        ${data.is_closed ? 'Closed' : data.time_remaining_formatted}
                    </div>
                    ${data.is_scored ? '<span class="badge badge-scored">Scored</span>' : ''}
                </div>
            </div>`;

        // Start countdown
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

        const days = Math.floor(remaining / 86400);
        const hours = Math.floor((remaining % 86400) / 3600);
        const mins = Math.floor((remaining % 3600) / 60);
        const secs = remaining % 60;

        let parts = [];
        if (days > 0) parts.push(`${days}d`);
        if (hours > 0) parts.push(`${hours}h`);
        parts.push(`${mins}m`);
        parts.push(`${secs}s`);

        el.textContent = parts.join(' ');
    }, 1000);
}

// ===== MY TEAM =====
async function loadMyTeam() {
    if (!currentUser) { navigate('login'); return; }
    await loadTeam();
}

async function loadTeam() {
    try {
        const response = await apiFetch('/users/me');
        if (!response.ok) return;
        const data = await response.json();
        currentTeam = data.team;
        currentUser = data.user;
        updateNav();
        renderMyTeam();
        renderChips();
    } catch (err) {
        console.error('Failed to load team:', err);
    }
}

async function renderMyTeam() {
    if (!currentTeam) return;

    // Update header stats
    document.getElementById('team-name').textContent = currentTeam.name;
    document.getElementById('team-budget').textContent = currentTeam.budget_remaining.toFixed(1);
    document.getElementById('team-points').textContent = currentTeam.total_points;
    document.getElementById('team-transfers').textContent = `${currentTeam.current_gw_transfers}/${currentTeam.free_transfers}`;

    // Load squad
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/squad`);
        if (!response.ok) return;
        const squad = await response.json();
        renderPitch(squad);
        renderBench(squad);

        // Load team value
        const valueResponse = await apiFetch(`/team-value/${currentTeam.id}`);
        if (valueResponse.ok) {
            const valueData = await valueResponse.json();
            document.getElementById('team-value').textContent = valueData.current_value.toFixed(1);
        }
    } catch (err) {
        console.error('Failed to load squad:', err);
    }
}

function renderPitch(squad) {
    const pitchPlayers = document.getElementById('pitch-players');
    if (!pitchPlayers) return;

    const starters = squad.filter(sp => sp.is_starting);
    const formation = document.getElementById('formation-select')?.value || '3-4-3';
    const [def, mid, fwd] = formation.split('-').map(Number);

    // Sort starters by position: GK first, then DEF, MID, FWD
    const posOrder = { 'GK': 0, 'DEF': 1, 'MID': 2, 'FWD': 3 };
    starters.sort((a, b) => {
        const pa = posOrder[a.player?.position || a.position] ?? 9;
        const pb = posOrder[b.player?.position || b.position] ?? 9;
        return pa - pb;
    });

    // Calculate positions on pitch
    const positions = [];
    // GK
    positions.push({ x: 50, y: 90 });
    // DEF
    for (let i = 0; i < def; i++) {
        positions.push({ x: 15 + (i * (70 / (def - 1 || 1))), y: 70 });
    }
    // MID
    for (let i = 0; i < mid; i++) {
        positions.push({ x: 15 + (i * (70 / (mid - 1 || 1))), y: 45 });
    }
    // FWD
    for (let i = 0; i < fwd; i++) {
        positions.push({ x: 20 + (i * (60 / (fwd - 1 || 1))), y: 20 });
    }

    let posIndex = 0;
    pitchPlayers.innerHTML = starters.map(sp => {
        const pos = positions[posIndex++] || { x: 50, y: 50 };
        const playerPos = sp.player?.position || sp.position || 'DEF';
        const posIcon = playerPos === 'GK' ? '🧤' : playerPos === 'DEF' ? '🛡️' : playerPos === 'MID' ? '⚡' : '⚽';
        return `
            <div class="pitch-player" style="left:${pos.x}%;top:${pos.y}%"
                 onclick="showPlayerMenu(${sp.id}, ${sp.player_id})"
                 data-squad-id="${sp.id}" data-player-id="${sp.player_id}">
                <div class="player-card ${playerPos.toLowerCase()} ${sp.was_autosub ? 'autosub' : ''}">
                    ${sp.is_captain ? '<div class="captain-badge">C</div>' : ''}
                    ${sp.is_vice_captain ? '<div class="vice-captain-badge">VC</div>' : ''}
                    <div class="player-pos-icon">${posIcon}</div>
                    <div class="player-name">${sp.player?.name || 'Unknown'}</div>
                    <div class="player-team">${sp.player?.team?.name || ''}</div>
                    <div class="player-points">${sp.gw_points || 0} pts</div>
                </div>
            </div>`;
    }).join('');
}

function renderBench(squad) {
    const benchGrid = document.getElementById('bench-grid');
    if (!benchGrid) return;

    const bench = squad.filter(sp => !sp.is_starting).sort((a, b) => (a.bench_priority || 99) - (b.bench_priority || 99));

    benchGrid.innerHTML = bench.map(sp => {
        const playerPos = sp.player?.position || sp.position || 'DEF';
        const posIcon = playerPos === 'GK' ? '🧤' : playerPos === 'DEF' ? '🛡️' : playerPos === 'MID' ? '⚡' : '⚽';
        return `
            <div class="bench-player">
                <div class="bench-priority">#${sp.bench_priority || '?'}</div>
                <div class="player-card ${playerPos.toLowerCase()} bench-card">
                    <div class="player-pos-icon">${posIcon}</div>
                    <div class="player-name">${sp.player?.name || 'Unknown'}</div>
                    <div class="player-team">${sp.player?.team?.name || ''}</div>
                </div>
            </div>`;
    }).join('');
}

function changeFormation() {
    renderMyTeam();
}

// ===== CHIPS =====
async function renderChips() {
    const chipsGrid = document.getElementById('chips-grid');
    if (!chipsGrid) return;

    try {
        const response = await apiFetch(`/users/${currentTeam.id}/chips`);
        if (!response.ok) return;
        const chips = await response.json();
        renderChipsGrid(chips);
    } catch (err) {
        console.error('Failed to load chips:', err);
    }
}

function renderChipsGrid(chips) {
    const chipsGrid = document.getElementById('chips-grid');
    if (!chipsGrid) return;

    const chipTypes = ['wildcard', 'free_hit', 'bench_boost', 'triple_captain'];
    const chipIcons = {
        wildcard: '🃏',
        free_hit: '⚡',
        bench_boost: '📈',
        triple_captain: '🎯'
    };
    const chipNames = {
        wildcard: 'Wildcard',
        free_hit: 'Free Hit',
        bench_boost: 'Bench Boost',
        triple_captain: 'Triple Captain'
    };

    chipsGrid.innerHTML = chipTypes.map(type => {
        const chip = chips.find(c => c.type === type);
        const isUsedFirst = chip?.first_half_used || false;
        const isUsedSecond = chip?.second_half_used || false;
        const isActive = chip?.active || false;
        const currentHalf = chip?.current_half || 'first';
        const isAvailable = currentHalf === 'first' ? !isUsedFirst : !isUsedSecond;

        return `
            <div class="chip-card ${type} ${isActive ? 'active' : ''} ${!isAvailable ? 'used' : ''}">
                <div class="chip-icon">${chipIcons[type]}</div>
                <div class="chip-name">${chipNames[type]}</div>
                <div class="chip-status">
                    ${isActive ? 'ACTIVE' : isAvailable ? 'Available' : 'Used'}
                </div>
                <div class="chip-halves">
                    <span class="chip-half ${isUsedFirst ? 'used' : ''}">${currentHalf === 'first' ? '▶' : ''}1st</span>
                    <span class="chip-half ${isUsedSecond ? 'used' : ''}">${currentHalf === 'second' ? '▶' : ''}2nd</span>
                </div>
                ${isActive ? `<button class="btn btn-sm btn-danger" onclick="cancelChip('${type}')">Cancel</button>` : ''}
                ${isAvailable && !isActive ? `<button class="btn btn-sm btn-success" onclick="activateChip('${type}')">Activate</button>` : ''}
            </div>`;
    }).join('');
}

async function activateChip(type) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/chips/activate/${type}`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast(`${type.replace('_', ' ')} activated!`, 'success');
            renderChips();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to activate chip', 'error');
        }
    } catch (err) {
        showToast('Failed to activate chip: ' + err.message, 'error');
    }
}

async function cancelChip(type) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/chips/cancel/${type}`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast(`${type.replace('_', ' ')} cancelled`, 'success');
            renderChips();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to cancel chip', 'error');
        }
    } catch (err) {
        showToast('Failed to cancel chip: ' + err.message, 'error');
    }
}

// ===== PLAYERS =====
async function loadPlayers() {
    const search = document.getElementById('player-search')?.value || '';
    const position = document.getElementById('player-position')?.value || '';
    const sort = document.getElementById('player-sort')?.value || 'total_points';

    let url = `/players?sort=${sort}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (position) url += `&position=${position}`;

    try {
        const response = await apiFetch(url);
        if (!response.ok) return;
        const players = await response.json();
        renderPlayers(players);
    } catch (err) {
        console.error('Failed to load players:', err);
    }
}

function renderPlayers(players) {
    const container = document.getElementById('players-container');
    if (!container) return;

    container.innerHTML = `
        <div class="players-table">
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>Name</th><th>Team</th><th>Pos</th>
                        <th>Price</th><th>TS</th><th>CS</th><th>A</th><th>F</th>
                        <th>Form</th><th>ICT</th><th>%Sel</th>
                    </tr>
                </thead>
                <tbody>
                    ${players.map(p => `
                        <tr onclick="showPlayerDetail(${p.id})">
                            <td>${p.id}</td>
                            <td class="player-name">${p.name}</td>
                            <td>${p.team?.name || ''}</td>
                            <td><span class="pos-badge ${p.position.toLowerCase()}">${p.position}</span></td>
                            <td>£${p.price.toFixed(1)}m</td>
                            <td>${p.total_points_season || 0}</td>
                            <td>${p.clean_sheets || 0}</td>
                            <td>${p.assists || 0}</td>
                            <td>${p.form || '0.0'}</td>
                            <td>${p.form || '0.0'}</td>
                            <td>${p.ict_index || '0.0'}</td>
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
    const teamFilter = document.getElementById('fixtures-team-filter')?.value || '';

    let url = '/fixtures/';
    if (gwSelect) url += `?gameweek_id=${gwSelect}`;

    try {
        const response = await apiFetch(url);
        if (!response.ok) return;
        const data = await response.json();
        renderFixtures(data.fixtures);

        // Load gameweeks for select
        loadGameweekOptions();
        loadTeamFilterOptions();
    } catch (err) {
        console.error('Failed to load fixtures:', err);
    }
}

function renderFixtures(fixtures) {
    const container = document.getElementById('fixtures-container');
    if (!container) return;

    if (!fixtures || fixtures.length === 0) {
        container.innerHTML = '<div class="empty-state">No fixtures available</div>';
        return;
    }

    // Group by gameweek
    const byGW = {};
    fixtures.forEach(f => {
        const gw = f.gameweek_id;
        if (!byGW[gw]) byGW[gw] = [];
        byGW[gw].push(f);
    });

    let html = '';
    Object.keys(byGW).sort((a, b) => a - b).forEach(gwId => {
        const gwFixtures = byGW[gwId];
        const firstFixture = gwFixtures[0];
        const date = firstFixture.date ? new Date(firstFixture.date).toLocaleDateString() : '';

        html += `<div class="fixture-gw">
            <h3>Gameweek ${gwId} ${date}</h3>
            <div class="fixture-list">`;

        gwFixtures.forEach(f => {
            const homeDiff = getDifficultyClass(f.home_difficulty);
            const awayDiff = getDifficultyClass(f.away_difficulty);

            html += `
                <div class="fixture-row">
                    <div class="fixture-team home">
                        <span class="team-name">${f.home_team}</span>
                        <span class="difficulty-badge ${homeDiff}">${f.home_difficulty}</span>
                    </div>
                    <div class="fixture-result">
                        ${f.played ? `<span class="score">${f.home_score}-${f.away_score}</span>` : '<span class="vs">vs</span>'}
                    </div>
                    <div class="fixture-team away">
                        <span class="difficulty-badge ${awayDiff}">${f.away_difficulty}</span>
                        <span class="team-name">${f.away_team}</span>
                    </div>
                </div>`;
        });

        html += '</div></div>';
    });

    container.innerHTML = html;
}

function getDifficultyClass(difficulty) {
    if (difficulty >= 5) return 'hh';
    if (difficulty >= 4) return 'h';
    if (difficulty >= 3) return 'm';
    if (difficulty >= 2) return 'e';
    return 'ee';
}

async function loadGameweekOptions() {
    const select = document.getElementById('fixtures-gw-select');
    if (!select) return;

    try {
        const response = await apiFetch('/gameweeks/');
        if (!response.ok) return;
        const data = await response.json();

        const currentValue = select.value;
        select.innerHTML = '<option value="">All Gameweeks</option>';
        data.gameweeks.forEach(gw => {
            select.innerHTML += `<option value="${gw.id}">GW ${gw.number}</option>`;
        });
        select.value = currentValue;
    } catch (err) {
        console.error('Failed to load GW options:', err);
    }
}

async function loadTeamFilterOptions() {
    const select = document.getElementById('fixtures-team-filter');
    if (!select) return;

    try {
        const response = await apiFetch('/teams/');
        if (!response.ok) return;
        const data = await response.json();

        const currentValue = select.value;
        select.innerHTML = '<option value="">All Teams</option>';
        data.teams.forEach(team => {
            select.innerHTML += `<option value="${team.id}">${team.name}</option>`;
        });
        select.value = currentValue;
    } catch (err) {
        console.error('Failed to load team options:', err);
    }
}

// ===== GAMEWEEKS =====
async function loadGameweeks() {
    try {
        const response = await apiFetch('/gameweeks/');
        if (!response.ok) return;
        const data = await response.json();
        renderGameweeks(data);

        // Load scoring progress
        loadScoringProgress(data.gameweeks);
    } catch (err) {
        console.error('Failed to load gameweeks:', err);
    }
}

function renderGameweeks(data) {
    const container = document.getElementById('gameweeks-container');
    if (!container) return;

    container.innerHTML = data.gameweeks.map(gw => `
        <div class="gw-card ${gw.closed ? 'closed' : ''} ${gw.scored ? 'scored' : ''}">
            <div class="gw-card-header">
                <h3>Gameweek ${gw.number}</h3>
                <span class="badge ${gw.closed ? 'badge-closed' : 'badge-open'}">${gw.closed ? 'Closed' : 'Open'}</span>
            </div>
            <div class="gw-card-body">
                <p>Deadline: ${gw.deadline ? new Date(gw.deadline).toLocaleString() : 'N/A'}</p>
                <p>Fixtures: ${gw.fixture_count || 0}</p>
                ${gw.scored ? '<span class="badge badge-scored">Scored</span>' : ''}
                ${gw.bonus_calculated ? '<span class="badge badge-bonus">Bonus Calculated</span>' : ''}
            </div>
        </div>
    `).join('');
}

async function loadScoringProgress(gameweeks) {
    const progressDiv = document.getElementById('scoring-progress');
    if (!progressDiv) return;

    const currentGW = gameweeks.find(gw => !gw.closed);
    if (!currentGW) {
        progressDiv.innerHTML = '';
        return;
    }

    try {
        const response = await apiFetch(`/fixtures/progress/${currentGW.id}`);
        if (!response.ok) return;
        const data = await response.json();

        progressDiv.innerHTML = `
            <div class="scoring-progress-bar">
                <div class="progress-label">
                    <span>Scoring Progress: ${data.fixtures_played}/${data.total_fixtures}</span>
                    <span>${data.progress_percent}%</span>
                </div>
                <div class="progress-track">
                    <div class="progress-fill" style="width: ${data.progress_percent}%"></div>
                </div>
            </div>`;
    } catch (err) {
        console.error('Failed to load scoring progress:', err);
    }
}

async function syncGameweeks() {
    try {
        const response = await apiFetch('/gameweeks/sync', { method: 'POST' });
        if (response.ok) {
            showToast('Fixtures synced!', 'success');
            loadGameweeks();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to sync', 'error');
        }
    } catch (err) {
        showToast('Sync failed: ' + err.message, 'error');
    }
}

// ===== HISTORY PAGE =====
async function loadHistoryPage() {
    if (!currentUser) { navigate('login'); return; }
    await loadHistorySummary();
    await loadGameweekOptionsForHistory();
    await loadTransferHistory();
}

async function loadHistorySummary() {
    const container = document.getElementById('history-summary');
    if (!container || !currentTeam) return;

    try {
        const response = await apiFetch(`/leaderboard/${currentTeam.user_id}/history`);
        if (!response.ok) return;
        const data = await response.json();

        if (!data.history || data.history.length === 0) {
            container.innerHTML = '<div class="empty-state">No history yet</div>';
            return;
        }

        // Summary stats
        const totalGWs = data.history.length;
        const avgPoints = (data.history.reduce((sum, h) => sum + h.points, 0) / totalGWs).toFixed(1);
        const bestGW = Math.max(...data.history.map(h => h.points));
        const worstGW = Math.min(...data.history.map(h => h.points));

        container.innerHTML = `
            <div class="history-stats-grid">
                <div class="history-stat-card">
                    <div class="stat-value">${data.history[totalGWs - 1]?.total_points || 0}</div>
                    <div class="stat-label">Total Points</div>
                </div>
                <div class="history-stat-card">
                    <div class="stat-value">${avgPoints}</div>
                    <div class="stat-label">Average/GW</div>
                </div>
                <div class="history-stat-card">
                    <div class="stat-value">${bestGW}</div>
                    <div class="stat-label">Best GW</div>
                </div>
                <div class="history-stat-card">
                    <div class="stat-value">${worstGW}</div>
                    <div class="stat-label">Worst GW</div>
                </div>
            </div>
            <div class="history-chart">
                ${data.history.map(h => `
                    <div class="history-bar" style="height: ${Math.max(5, h.points * 2)}%" title="GW ${h.gameweek}: ${h.points} pts">
                        <span class="bar-label">GW${h.gameweek}</span>
                        <span class="bar-value">${h.points}</span>
                    </div>
                `).join('')}
            </div>`;
    } catch (err) {
        console.error('Failed to load history:', err);
    }
}

async function loadGameweekOptionsForHistory() {
    const select = document.getElementById('history-gw-select');
    if (!select) return;

    try {
        const response = await apiFetch('/gameweeks/');
        if (!response.ok) return;
        const data = await response.json();

        select.innerHTML = '<option value="">Select Gameweek</option>';
        data.gameweeks.forEach(gw => {
            select.innerHTML += `<option value="${gw.id}">GW ${gw.number}</option>`;
        });
    } catch (err) {
        console.error('Failed to load GW options:', err);
    }
}

async function loadGameweekBreakdown() {
    const select = document.getElementById('history-gw-select');
    const breakdown = document.getElementById('history-breakdown');
    if (!select || !breakdown || !currentTeam) return;

    const gwId = select.value;
    if (!gwId) {
        breakdown.innerHTML = '<div class="empty-state">Select a gameweek to see the breakdown</div>';
        return;
    }

    try {
        const response = await apiFetch(`/gameweek-history/${currentTeam.id}/${gwId}`);
        if (!response.ok) return;
        const data = await response.json();

        breakdown.innerHTML = `
            <div class="gw-breakdown-header">
                <h3>Gameweek ${data.gameweek} Breakdown</h3>
                <div class="breakdown-stats">
                    <span>Total: ${data.total_points} pts</span>
                    <span>Starting: ${data.starting_points}</span>
                    <span>Bench: ${data.bench_points}</span>
                    ${data.chip_used ? `<span class="chip-badge">${data.chip_used}</span>` : ''}
                </div>
            </div>
            <div class="player-breakdown-grid">
                ${data.player_breakdown.map(p => `
                    <div class="player-breakdown-card ${p.is_starting ? 'starting' : 'bench'}">
                        <div class="pb-name">${p.name}</div>
                        <div class="pb-details">
                            <span class="pos-badge ${p.position.toLowerCase()}">${p.position}</span>
                            ${p.is_captain ? '<span class="captain-badge-sm">C</span>' : ''}
                            ${p.is_vice_captain ? '<span class="vice-badge-sm">VC</span>' : ''}
                            ${p.was_autosub ? '<span class="autosub-badge">AUTO</span>' : ''}
                        </div>
                        <div class="pb-stats">
                            <span>${p.goals}G</span>
                            <span>${p.assists}A</span>
                            <span>${p.minutes}min</span>
                            ${p.bonus > 0 ? `<span class="bonus-badge">+${p.bonus}</span>` : ''}
                        </div>
                        <div class="pb-points ${p.points > 0 ? 'positive' : ''}">${p.points} pts</div>
                    </div>
                `).join('')}
            </div>`;
    } catch (err) {
        console.error('Failed to load breakdown:', err);
        breakdown.innerHTML = '<div class="error-state">Failed to load breakdown</div>';
    }
}

async function loadTransferHistory() {
    const container = document.getElementById('transfer-history-container');
    if (!container || !currentTeam) return;

    try {
        const response = await apiFetch(`/gameweek-history/transfer-history/${currentTeam.id}`);
        if (!response.ok) return;
        const data = await response.json();

        if (!data.transfers || data.transfers.length === 0) {
            container.innerHTML = '<div class="empty-state">No transfers yet</div>';
            return;
        }

        container.innerHTML = data.transfers.map(t => `
            <div class="transfer-history-row">
                <span class="transfer-gw">GW ${t.gameweek || '?'}</span>
                <span class="transfer-in">➕ ${t.player_in?.name || '?'}</span>
                ${t.player_out ? `<span class="transfer-out">➖ ${t.player_out.name} (${t.player_out.points_scored} pts)</span>` : ''}
                ${t.is_wildcard ? '<span class="badge badge-wildcard">WC</span>' : ''}
                ${t.is_free_hit ? '<span class="badge badge-freehit">FH</span>' : ''}
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to load transfer history:', err);
    }
}

// ===== LEADERBOARD =====
async function loadLeaderboard() {
    try {
        const response = await apiFetch('/leaderboard/?limit=100');
        if (!response.ok) return;
        const data = await response.json();
        renderLeaderboard(data);

        // Load user rank if logged in
        if (currentUser) {
            loadUserRank();
        }
    } catch (err) {
        console.error('Failed to load leaderboard:', err);
    }
}

function renderLeaderboard(data) {
    const container = document.getElementById('leaderboard-container');
    if (!container) return;

    // Stats
    const statsDiv = document.getElementById('leaderboard-stats');
    if (statsDiv) {
        statsDiv.innerHTML = `<span>Total Teams: ${data.total_teams}</span>`;
    }

    container.innerHTML = `
        <div class="leaderboard-table">
            <table>
                <thead>
                    <tr><th>Rank</th><th>Manager</th><th>Team</th><th>Total</th><th>GW</th></tr>
                </thead>
                <tbody>
                    ${data.entries.map(e => `
                        <tr>
                            <td>${e.rank}</td>
                            <td>${e.username}</td>
                            <td>${e.team_name}</td>
                            <td class="points">${e.total_points}</td>
                            <td>${e.gameweek_points ?? '-'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
}

async function loadUserRank() {
    const statsDiv = document.getElementById('leaderboard-stats');
    if (!statsDiv || !currentTeam) return;

    try {
        const response = await apiFetch(`/leaderboard/${currentTeam.user_id}/rank`);
        if (!response.ok) return;
        const data = await response.json();

        statsDiv.innerHTML = `
            <span>Total Teams: ${data.total_teams}</span>
            <span>Your Rank: #${data.rank}</span>
            <span>Percentile: ${data.percentile}%</span>
            ${data.rank_change ? `<span class="rank-change ${data.rank_change > 0 ? 'up' : data.rank_change < 0 ? 'down' : ''}">${data.rank_change > 0 ? '↑' : data.rank_change < 0 ? '↓' : '='} ${Math.abs(data.rank_change)}</span>` : ''}
        `;
    } catch (err) {
        console.error('Failed to load user rank:', err);
    }
}

// ===== DREAM TEAM =====
async function loadDreamTeamPage() {
    const select = document.getElementById('dream-team-gw-select');
    if (!select) return;

    try {
        const response = await apiFetch('/gameweeks/');
        if (!response.ok) return;
        const data = await response.json();

        const currentValue = select.value;
        select.innerHTML = '<option value="">Select Gameweek</option>';
        data.gameweeks.forEach(gw => {
            select.innerHTML += `<option value="${gw.id}">GW ${gw.number}</option>`;
        });
        select.value = currentValue;

        if (currentValue) {
            loadDreamTeam();
        }
    } catch (err) {
        console.error('Failed to load GW options:', err);
    }
}

async function loadDreamTeam() {
    const select = document.getElementById('dream-team-gw-select');
    const container = document.getElementById('dream-team-players');
    const totalDiv = document.getElementById('dream-team-total');

    if (!select || !container) return;

    const gwId = select.value;
    if (!gwId) {
        container.innerHTML = '<div class="empty-state">Select a gameweek</div>';
        return;
    }

    try {
        const response = await apiFetch(`/dream-team/${gwId}`);
        if (!response.ok) return;
        const data = await response.json();

        if (!data.players || data.players.length === 0) {
            container.innerHTML = '<div class="empty-state">Dream Team not yet calculated</div>';
            return;
        }

        // Render dream team on pitch
        const positions = data.players.map((p, i) => ({
            x: 50, y: 90  // GK
        }))[0];

        // Simple formation rendering
        const defPositions = data.players.filter(p => p.position === 'DEF');
        const midPositions = data.players.filter(p => p.position === 'MID');
        const fwdPositions = data.players.filter(p => p.position === 'FWD');

        let html = '';
        const gk = data.players.find(p => p.position === 'GK');
        if (gk) {
            html += createDreamTeamPlayer(gk, 50, 90);
        }

        defPositions.forEach((p, i) => {
            const x = 15 + (i * (70 / (defPositions.length - 1 || 1)));
            html += createDreamTeamPlayer(p, x, 70);
        });

        midPositions.forEach((p, i) => {
            const x = 15 + (i * (70 / (midPositions.length - 1 || 1)));
            html += createDreamTeamPlayer(p, x, 45);
        });

        fwdPositions.forEach((p, i) => {
            const x = 20 + (i * (60 / (fwdPositions.length - 1 || 1)));
            html += createDreamTeamPlayer(p, x, 20);
        });

        container.innerHTML = html;

        if (totalDiv) {
            totalDiv.innerHTML = `<div class="dream-team-total-score">Total: ${data.total_points} points</div>`;
        }
    } catch (err) {
        console.error('Failed to load dream team:', err);
    }
}

function createDreamTeamPlayer(player, x, y) {
    return `
        <div class="dream-team-player" style="left:${x}%;top:${y}%">
            <div class="dream-player-card">
                <div class="dream-player-name">${player.name}</div>
                <div class="dream-player-team">${player.team_name}</div>
                <div class="dream-player-points">${player.points} pts</div>
            </div>
        </div>`;
}

// ===== LEAGUES =====
async function loadLeagues() {
    if (!currentUser) { navigate('login'); return; }
    const container = document.getElementById('leagues-container');
    if (!container) return;

    try {
        const response = await apiFetch('/mini_leagues/');
        if (!response.ok) return;
        const data = await response.json();

        if (!data.leagues || data.leagues.length === 0) {
            container.innerHTML = '<div class="empty-state">No leagues yet. Create or join one!</div>';
            return;
        }

        container.innerHTML = data.leagues.map(l => `
            <div class="league-card">
                <h3>${l.name}</h3>
                <p>Members: ${l.members?.length || 0}</p>
                <p>Code: ${l.code}</p>
                <div class="league-standings">
                    ${l.standings?.map(s => `
                        <div class="standings-row">
                            <span class="rank">#${s.rank}</span>
                            <span>${s.team_name}</span>
                            <span class="points">${s.total_points} pts</span>
                        </div>
                    `).join('') || ''}
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to load leagues:', err);
    }
}

function showCreateLeague() {
    const name = prompt('League name:');
    if (!name) return;

    fetch(`${API_BASE}/mini_leagues/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getToken()}`
        },
        body: JSON.stringify({ name, is_h2h: false })
    }).then(r => r.json()).then(data => {
        showToast(`League created! Code: ${data.code}`, 'success');
        loadLeagues();
    });
}

function showJoinLeague() {
    const code = prompt('Enter league code:');
    if (!code) return;

    fetch(`${API_BASE}/mini_leagues/${code}/join`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${getToken()}`
        }
    }).then(r => r.json()).then(data => {
        showToast('Joined league!', 'success');
        loadLeagues();
    });
}

// ===== TRANSFERS =====
async function loadTransfersPage() {
    if (!currentUser) { navigate('login'); return; }
    await loadTeam();
}

async function searchTransferPlayers() {
    const search = document.getElementById('transfer-search-input')?.value || '';
    const position = document.getElementById('transfer-position-filter')?.value || '';

    let url = `/players?limit=50`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (position) url += `&position=${position}`;

    try {
        const response = await apiFetch(url);
        if (!response.ok) return;
        const players = await response.json();

        const container = document.getElementById('transfer-results');
        if (!container) return;

        // Check which players are in our squad
        const squadIds = currentTeam?.squad?.map(sp => sp.player_id) || [];

        container.innerHTML = players.map(p => {
            const isInSquad = squadIds.includes(p.id);
            return `
                <div class="transfer-player-row ${isInSquad ? 'in-squad' : ''}">
                    <span class="pos-badge ${p.position.toLowerCase()}">${p.position}</span>
                    <span class="player-name">${p.name}</span>
                    <span>${p.team?.name || ''}</span>
                    <span>£${p.price.toFixed(1)}m</span>
                    <span>${p.total_points_season || 0} pts</span>
                    <span>${(p.selected_by_percent || 0).toFixed(1)}%</span>
                    ${isInSquad
                        ? `<button class="btn btn-sm btn-outline" onclick="transferOut(${p.id})">Transfer Out</button>`
                        : `<button class="btn btn-sm btn-primary" onclick="transferIn(${p.id})">Transfer In</button>`
                    }
                </div>`;
        }).join('');
    } catch (err) {
        console.error('Failed to search players:', err);
    }
}

async function transferIn(playerId) {
    if (!currentTeam) return;
    try {
        const response = await apiFetch('/transfers/player', {
            method: 'POST',
            body: JSON.stringify({
                fantasy_team_id: currentTeam.id,
                player_in_id: playerId,
            }),
        });
        if (response.ok) {
            showToast('Player transferred in!', 'success');
            loadTeam();
            searchTransferPlayers();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Transfer failed', 'error');
        }
    } catch (err) {
        showToast('Transfer failed: ' + err.message, 'error');
    }
}

async function transferOut(playerId) {
    if (!currentTeam) return;
    const confirmOut = confirm('Transfer this player out?');
    if (!confirmOut) return;

    try {
        const response = await apiFetch('/transfers/player', {
            method: 'POST',
            body: JSON.stringify({
                fantasy_team_id: currentTeam.id,
                player_out_id: playerId,
            }),
        });
        if (response.ok) {
            showToast('Player transferred out!', 'success');
            loadTeam();
            searchTransferPlayers();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Transfer failed', 'error');
        }
    } catch (err) {
        showToast('Transfer failed: ' + err.message, 'error');
    }
}

// ===== PLAYER MENU =====
async function showPlayerMenu(squadId, playerId) {
    if (!currentTeam) return;

    const actions = [
        { label: 'Set Captain', action: () => setCaptain(squadId) },
        { label: 'Set Vice-Captain', action: () => setViceCaptain(squadId) },
        { label: 'Bench Player', action: () => benchPlayer(squadId) },
        { label: 'Start Player', action: () => startPlayer(squadId) },
    ];

    const overlay = document.getElementById('modal-overlay');
    const content = document.getElementById('modal-content');

    content.innerHTML = `
        <div class="player-menu-modal">
            ${actions.map(a => `<button class="btn btn-block" onclick="${a.action.name}(); closeModal();">${a.label}</button>`).join('')}
            <button class="btn btn-outline btn-block" onclick="closeModal()">Close</button>
        </div>`;

    overlay.style.display = 'block';
    content.style.display = 'block';
}

function closeModal() {
    document.getElementById('modal-overlay').style.display = 'none';
    document.getElementById('modal-content').style.display = 'none';
}

async function setCaptain(squadId) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/captain/${squadId}`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast('Captain set!', 'success');
            renderMyTeam();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to set captain', 'error');
        }
    } catch (err) {
        showToast('Failed: ' + err.message, 'error');
    }
}

async function setViceCaptain(squadId) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/vice-captain/${squadId}`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast('Vice-captain set!', 'success');
            renderMyTeam();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to set vice-captain', 'error');
        }
    } catch (err) {
        showToast('Failed: ' + err.message, 'error');
    }
}

async function benchPlayer(squadId) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/squad/${squadId}/bench`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast('Player benched!', 'success');
            renderMyTeam();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed', 'error');
        }
    } catch (err) {
        showToast('Failed: ' + err.message, 'error');
    }
}

async function startPlayer(squadId) {
    try {
        const response = await apiFetch(`/users/${currentTeam.id}/squad/${squadId}/start`, {
            method: 'POST',
        });
        if (response.ok) {
            showToast('Player started!', 'success');
            renderMyTeam();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed', 'error');
        }
    } catch (err) {
        showToast('Failed: ' + err.message, 'error');
    }
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

// ===== NOTIFICATIONS =====
async function loadNotifications() {
    if (!currentTeam) return;
    const container = document.getElementById('notifications-container');
    if (!container) return;

    try {
        const response = await apiFetch(`/notifications/team/${currentTeam.id}`);
        if (!response.ok) return;
        const data = await response.json();
        renderNotifications(data);
    } catch (err) {
        console.error('Failed to load notifications:', err);
    }
}

function renderNotifications(data) {
    const container = document.getElementById('notifications-container');
    if (!container) return;

    if (!data.notifications || data.notifications.length === 0) {
        container.innerHTML = '<p class="empty-state">No notifications yet.</p>';
        return;
    }

    const iconMap = {
        'gameweek_result': '\u{1F4CA}',
        'chip_used': '\u{1F0CF}',
        'price_change': '\u{1F4B0}',
        'injury': '\u{1F4A5}',
    };

    container.innerHTML = data.notifications.map(n => `
        <div class="notification-item ${n.read ? 'read' : 'unread'}">
            <div class="notification-icon">${iconMap[n.type] || '\u{1F4E1}'}</div>
            <div class="notification-content">
                <div class="notification-title">${n.title}</div>
                <div class="notification-message">${n.message}</div>
                <div class="notification-time">${n.timestamp ? new Date(n.timestamp).toLocaleString() : ''}</div>
            </div>
        </div>
    `).join('');
}

async function markAllNotificationsRead() {
    if (!currentTeam) return;
    try {
        await apiFetch(`/notifications/team/${currentTeam.id}/mark-all-read`, { method: 'POST' });
        showToast('All notifications marked as read', 'success');
        loadNotifications();
    } catch (err) {
        console.error('Failed to mark read:', err);
    }
}

// ===== PLAYER DETAIL MODAL =====
async function showPlayerDetail(playerId) {
    try {
        const response = await apiFetch(`/players/${playerId}/detail`);
        if (!response.ok) return;
        const data = await response.json();
        renderPlayerDetailModal(data);
    } catch (err) {
        console.error('Failed to load player detail:', err);
    }
}

function renderPlayerDetailModal(data) {
    const { player, form_guide, gw_history, upcoming_fixtures, ownership } = data;
    const priceChangeClass = player.price_change > 0 ? 'price-up' : player.price_change < 0 ? 'price-down' : '';
    const priceChangeText = player.price_change > 0 ? `+${player.price_change * 0.1}` : (player.price_change * 0.1).toFixed(1);

    // Form guide display
    const formDisplay = form_guide.map(f => {
        const cls = f.points >= 10 ? 'form-high' : f.points >= 5 ? 'form-mid' : 'form-low';
        return `<span class="form-badge ${cls}">${f.points}</span>`;
    }).join(' ');

    // Upcoming fixtures display
    const fixturesDisplay = (upcoming_fixtures || []).map(f => {
        const difficultyClass = f.difficulty <= 2 ? 'easy' : f.difficulty <= 3 ? 'medium' : 'hard';
        const homeAway = f.is_home ? 'H' : 'A';
        return `<span class="fixture-badge ${difficultyClass}">${homeAway} ${f.opponent} (GW${f.gameweek})</span>`;
    }).join(' ');

    const content = document.getElementById('modal-content');
    content.style.display = 'block';
    content.style.maxWidth = '600px';
    content.innerHTML = `
        <div class="player-detail-modal">
            <div class="player-detail-header">
                <div class="player-detail-info">
                    <h2>${player.name}</h2>
                    <div class="player-detail-meta">
                        <span class="pos-badge ${player.position.toLowerCase()}">${player.position}</span>
                        <span>${player.team_name}</span>
                    </div>
                    ${player.is_injured ? '<span class="injury-badge">INJURED - ' + (player.injury_status || '') + '</span>' : ''}
                </div>
                <div class="player-detail-price">
                    <div class="price-main">£${player.price.toFixed(1)}m</div>
                    <div class="price-change ${priceChangeClass}">${priceChangeText > 0 ? '+' : ''}${priceChangeText}m</div>
                </div>
            </div>

            <div class="player-detail-stats">
                <div class="stat-grid">
                    <div class="stat-item"><div class="stat-label">Total Points</div><div class="stat-value">${player.total_points || 0}</div></div>
                    <div class="stat-item"><div class="stat-label">Form</div><div class="stat-value">${player.form || '0.0'}</div></div>
                    <div class="stat-item"><div class="stat-label">ICT Index</div><div class="stat-value">${player.ict_index || '0.0'}</div></div>
                    <div class="stat-item"><div class="stat-label">Selected</div><div class="stat-value">${player.selected_by_percent?.toFixed(1) || 0}%</div></div>
                    <div class="stat-item"><div class="stat-label">Goals</div><div class="stat-value">${player.goals || 0}</div></div>
                    <div class="stat-item"><div class="stat-label">Assists</div><div class="stat-value">${player.assists || 0}</div></div>
                    <div class="stat-item"><div class="stat-label">Clean Sheets</div><div class="stat-value">${player.clean_sheets || 0}</div></div>
                    <div class="stat-item"><div class="stat-label">Bonus</div><div class="stat-value">${player.bonus || 0}</div></div>
                </div>
            </div>

            ${formDisplay ? `<div class="player-detail-section"><h3>Form (Last 5 GWs)</h3><div class="form-guide">${formDisplay}</div></div>` : ''}
            ${fixturesDisplay ? `<div class="player-detail-section"><h3>Upcoming Fixtures</h3><div class="fixtures-list">${fixturesDisplay}</div></div>` : ''}

            ${gw_history && gw_history.length > 0 ? `
                <div class="player-detail-section">
                    <h3>Gameweek History</h3>
                    <table class="history-table">
                        <thead><tr><th>GW</th><th>Pts</th><th>A</th><th>B</th><th>Min</th></tr></thead>
                        <tbody>
                            ${gw_history.slice(-10).map(h => `<tr><td>${h.gameweek}</td><td>${h.points || 0}</td><td>${h.assists || 0}</td><td>${h.bonus || 0}</td><td>${h.minutes || 0}</td></tr>`).join('')}
                        </tbody>
                    </table>
                </div>
            ` : ''}

            <div class="player-detail-footer">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        </div>
    `;
    document.getElementById('modal-overlay').style.display = 'block';
}

// ===== TEAM DETAILS MODAL =====
function showTeamDetails() {
    if (!currentTeam) return;

    // Fetch all teams for club selection dropdown
    fetch(`${API_BASE}/teams/`).then(r => r.json()).then(teams => {
        const content = document.getElementById('modal-content');
        content.style.display = 'block';
        content.style.maxWidth = '500px';
        content.innerHTML = `
            <div class="team-details-modal">
                <h2>Team Details</h2>
                <form onsubmit="updateTeamDetails(event, ${JSON.stringify(teams).replace(/"/g, '&quot;')})">
                    <div class="form-group">
                        <label>Team Name</label>
                        <input type="text" id="team-details-name" value="${currentTeam.name || ''}" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>Supported Club</label>
                        <select id="team-details-club" class="form-input">
                            <option value="">-- Select Club --</option>
                            ${teams.map(t => `<option value="${t.id}" ${currentTeam.supported_club_id === t.id ? 'selected' : ''}>${t.name}</option>`).join('')}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">Save Changes</button>
                </form>
                <button class="btn btn-secondary btn-block" style="margin-top:10px" onclick="closeModal()">Cancel</button>
            </div>
        `;
        document.getElementById('modal-overlay').style.display = 'block';
    });
}

async function updateTeamDetails(e, teams) {
    e.preventDefault();
    const teamName = document.getElementById('team-details-name').value;
    const clubId = document.getElementById('team-details-club').value;

    try {
        const params = new URLSearchParams();
        if (teamName) params.append('team_name', teamName);
        if (clubId) params.append('supported_club_id', clubId);

        const response = await fetch(`${API_BASE}/users/${currentUser.id}/team/update?${params.toString()}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });

        if (response.ok) {
            showToast('Team details updated!', 'success');
            closeModal();
            loadTeam();
        } else {
            const err = await response.json();
            showToast(err.detail || 'Failed to update', 'error');
        }
    } catch (err) {
        showToast('Failed: ' + err.message, 'error');
    }
}

// ===== CHIP CONFIRMATION MODAL =====
function confirmChipActivation(chipType) {
    const chipNames = {
        wildcard: 'Wildcard',
        free_hit: 'Free Hit',
        bench_boost: 'Bench Boost',
        triple_captain: 'Triple Captain',
    };
   const chipDescriptions = {
        wildcard: 'Unlimited permanent transfers at no cost for this gameweek.',
        free_hit: 'One-off squad change that reverts next gameweek. Cannot be cancelled once confirmed.',
        bench_boost: 'All 15 players points count for this gameweek.',
        triple_captain: 'Your captain points are tripled instead of doubled.',
    };

    const content = document.getElementById('modal-content');
    content.style.display = 'block';
    content.style.maxWidth = '450px';
    content.innerHTML = `
        <div class="chip-confirm-modal">
            <h2>Activate ${chipNames[chipType]}</h2>
            <p>${chipDescriptions[chipType]}</p>
            ${chipType === 'free_hit' ? '<p class="warning-text">Warning: Free Hit cannot be cancelled once confirmed.</p>' : '<p class="info-text">You can cancel this chip before the gameweek deadline.</p>'}
            <div style="display:flex;gap:10px;margin-top:20px">
                <button class="btn btn-success btn-block" onclick="activateChip('${chipType}'); closeModal();">Activate</button>
                <button class="btn btn-secondary btn-block" onclick="closeModal()">Cancel</button>
            </div>
        </div>
    `;
    document.getElementById('modal-overlay').style.display = 'block';
}

// ===== SCORING PROGRESS BAR =====
function updateScoringProgress(data) {
    const progressEl = document.getElementById('scoring-progress');
    if (!progressEl) return;

    if (!data || data.percentage === undefined) return;

    progressEl.innerHTML = `
        <div class="progress-bar-container">
            <div class="progress-bar-header">
                <span class="progress-label">Scoring Progress</span>
                <span class="progress-value">${data.completed_fixtures}/${data.total_fixtures} fixtures (${data.percentage}%)</span>
            </div>
            <div class="progress-bar-track">
                <div class="progress-bar-fill" style="width: ${data.percentage}%"></div>
            </div>
        </div>
    `;
}

// ===== RANK DISPLAY =====
function renderRankDisplay() {
    if (!currentTeam) return;
    const rankEl = document.getElementById('rank-display');
    if (!rankEl) return;

    rankEl.innerHTML = `
        <div class="rank-item">
            <span class="rank-label">Overall Rank</span>
            <span class="rank-value">#${currentTeam.overall_rank || 'N/A'}</span>
        </div>
        ${currentTeam.supported_club_name ? `
        <div class="rank-item">
            <span class="rank-label">${currentTeam.supported_club_name} Rank</span>
            <span class="rank-value" id="club-rank">Loading...</span>
        </div>
    ` : ''}
    `;
}

// ===== MODAL =====
function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

// ===== GW RECAP =====
async function loadGWRecap() {
    if (!currentTeam) return;
    const container = document.getElementById('recap-container');
    if (!container) return;
    container.innerHTML = '<p class="empty-state">Loading gameweek recap...</p>';

    try {
        // Load gameweek dropdown
        const dropdown = document.getElementById('recap-gw-dropdown');
        if (dropdown) {
            const gwResponse = await apiFetch('/gameweek-history/gameweeks');
            if (gwResponse.ok) {
                const gws = await gwResponse.json();
                dropdown.innerHTML = gws.map(gw => `<option value="${gw.id}" ${gw.current ? 'selected' : ''}>Gameweek ${gw.number}</option>`).join('');
            }
        }

        // Load recap for current gameweek
        const recapResponse = await apiFetch(`/gameweek-history/${currentTeam.id}/current-gw-recap`);
        if (!recapResponse.ok) { container.innerHTML = '<p class="empty-state">No recap available.</p>'; return; }

        const data = await recapResponse.json();

        // Update scoring progress
        updateScoringProgress(data);
        renderRankDisplay();

        container.innerHTML = `
            <div class="recap-header">
                <h3>Gameweek ${data.gameweek_number} Recap</h3>
                <div class="recap-total">
                    <span class="recap-total-label">Total Points</span>
                    <span class="recap-total-value">${data.total_points || 0}</span>
                </div>
            </div>
            <div class="player-breakdown-grid">
                ${(data.squad_recap || []).map(sp => {
                    const posIcon = sp.position === 'GK' ? '🧤' : sp.position === 'DEF' ? '🛡️' : sp.position === 'MID' ? '⚡' : '⚽';
                    const details = [];
                    if (sp.goals) details.push(`${sp.goals}G`);
                    if (sp.assists) details.push(`${sp.assists}A`);
                    if (sp.clean_sheet) details.push('CS');
                    if (sp.bonus) details.push(`+${sp.bonus}B`);
                    if (sp.was_captain) details.push('C');
                    return `
                        <div class="player-breakdown-card">
                            <div class="player-breakdown-avatar">${posIcon}</div>
                            <div class="player-breakdown-info">
                                <div class="player-breakdown-name">${sp.player?.name || 'Unknown'}</div>
                                <div class="player-breakdown-team">${sp.player?.team?.name || ''} ${sp.was_autosub ? '(AUTOSUB)' : ''}</div>
                                <div class="player-breakdown-details">${details.join(' ')}</div>
                            </div>
                            <div class="player-breakdown-points">${sp.points || 0}</div>
                        </div>`;
                }).join('')}
            </div>
        `;
    } catch (err) {
        console.error('Failed to load recap:', err);
        container.innerHTML = '<p class="empty-state">Failed to load recap.</p>';
    }
}

// ===== H2H PAGE =====
async function loadH2HPage() {
    if (!currentTeam) return;

    try {
        // Load H2H league info
        const h2hResponse = await apiFetch(`/h2h/user/${currentTeam.id}`);
        if (!h2hResponse.ok) {
            const overview = document.getElementById('h2h-season-overview');
            if (overview) overview.innerHTML = '<p class="empty-state">Not in an H2H league yet.</p>';
            return;
        }
        const h2hData = await h2hResponse.json();

        // Season overview
        const overview = document.getElementById('h2h-season-overview');
        if (overview) {
            overview.innerHTML = `
                <div class="h2h-overview">
                    <div class="h2h-stat-card"><div class="h2h-stat-value">${h2hData.wins || 0}</div><div class="h2h-stat-label">Wins</div></div>
                    <div class="h2h-stat-card"><div class="h2h-stat-value">${h2hData.draws || 0}</div><div class="h2h-stat-label">Draws</div></div>
                    <div class="h2h-stat-card"><div class="h2h-stat-value">${h2hData.losses || 0}</div><div class="h2h-stat-label">Losses</div></div>
                    <div class="h2h-stat-card"><div class="h2h-stat-value">${h2hData.h2h_points || 0}</div><div class="h2h-stat-label">H2H Points</div></div>
                    <div class="h2h-stat-card"><div class="h2h-stat-value">${h2hData.round || 0}</div><div class="h2h-stat-label">Round</div></div>
                </div>
            `;
        }

        // Current matchup
        const matchup = document.getElementById('h2h-current-matchup');
        if (matchup && h2hData.current_opponent) {
            matchup.innerHTML = `
                <div class="h2h-matchup">
                    <div class="h2h-team">
                        <div class="h2h-team-name">${currentTeam.name}</div>
                        <div class="h2h-team-records">${h2hData.wins}W-${h2hData.draws}D-${h2hData.losses}L</div>
                        <div class="h2h-points">${h2hData.current_points || 0} pts</div>
                    </div>
                    <div class="h2h-vs">VS</div>
                    <div class="h2h-team">
                        <div class="h2h-team-name">${h2hData.current_opponent.name}</div>
                        <div class="h2h-team-records">${h2hData.current_opponent.wins}W-${h2hData.current_opponent.draws}D-${h2hData.current_opponent.losses}L</div>
                        <div class="h2h-points">${h2hData.current_opponent.current_points || 0} pts</div>
                    </div>
                </div>
            `;
        }

        // Bracket
        const bracket = document.getElementById('h2h-bracket');
        if (bracket && h2hData.bracket) {
            let bracketHTML = '<div class="h2h-bracket">';
            for (const [roundName, matches] of Object.entries(h2hData.bracket)) {
                bracketHTML += `<div class="h2h-bracket-round"><h3>${roundName}</h3>`;
                for (const m of matches) {
                    const resultClass = m.result === 'win' ? 'win' : m.result === 'draw' ? 'draw' : 'loss';
                    bracketHTML += `
                        <div class="h2h-bracket-match">
                            <div class="bracket-team ${m.team1_win ? 'winner' : m.team1_loss ? 'loser' : ''}">${m.team1_name}</div>
                            <div class="bracket-score">${m.team1_points || '-'} - ${m.team2_points || '-'}</div>
                            <div class="bracket-team ${m.team2_win ? 'winner' : m.team2_loss ? 'loser' : ''}">${m.team2_name}</div>
                            ${m.result ? `<span class="bracket-result ${resultClass}">${m.result.toUpperCase()}</span>` : ''}
                        </div>
                    `;
                }
                bracketHTML += '</div>';
            }
            bracketHTML += '</div>';
            bracket.innerHTML = bracketHTML;
        }
    } catch (err) {
        console.error('Failed to load H2H:', err);
    }
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
    updateNav();
    
    // Check for stored token and load team if logged in
    if (getToken()) {
        loadTeam().then(() => {
            if (currentTeam) {
                navigate('my-team');
            }
        });
    } else {
        loadHomePage();
    }
});
