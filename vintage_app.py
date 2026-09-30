"""Compatibility landing page for the retired standalone deployment."""
import streamlit as st

st.set_page_config(page_title="Vintage analysis has moved", layout="centered")
st.title("Vintage analysis is now part of LendSight")
st.write("Use one place to inspect synthetic vintages, adjust default and payoff curves, forecast revenue and export Excel.")
st.link_button("Open Vintage Analysis & Overlay", "https://cpropel-poc2.streamlit.app/?page=vintage", type="primary")
